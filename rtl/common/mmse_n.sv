// Parameterised N x N MMSE/ZF (2 <= N <= 8), bit-exact with common/python/mmse_n_fixed.py:
// H Q15 -> G = H^H H + L I (Q30, exact) -> block-normalised A (Q30, max diagonal in [1,2))
// -> Hermitian Gaussian elimination with real pivots -> back substitution -> W Q24 (signed 64).
// Configuration performs one complex multiply-accumulate per clock; the multipliers
// m = conj(A[k][i]) << 30 / d_k and the solutions X = acc / d_k use one shared sequential
// nearest-even divider (ACCW + 3 clocks per component). Configuration is not on the sample path. Each accepted
// observation j updates all N output accumulators (N complex MACs per clock), so a
// configured block sustains one sample per clock. This source makes no physical timing claim.
// cfg_last belongs to H[N-1][N-1] (the N*N-th coefficient, row-major); lambda is unsigned Q30
// there. Frames contain complete observation N-tuples; only the N-th sample may carry s_last.
// Configuration errors (wrong length, nonpositive pivot, any internal width) and early
// s_last are sticky until reset.
module mmse_n #(
  parameter int N=4,
  parameter bit RESET_ACTIVE=1,
  parameter int GRAM_ACC_WIDTH=36+$clog2(N+1),
  parameter int SUM_WIDTH=82+$clog2(N+1),
  parameter int A_PRODUCT_WIDTH=83,B_PRODUCT_WIDTH=121,
  parameter int A_UPDATE_WIDTH=53,B_UPDATE_WIDTH=91,
  parameter int NORM_WIDTH=70,WEIGHT_WIDTH=87,MULT_NUM_WIDTH=65,
  parameter int BACK_PRODUCT_WIDTH=107,BACK_ACC_WIDTH=106+$clog2(N)
)(
  input logic clk,rst,
  input logic cfg_valid,cfg_last,
  input logic signed [17:0] cfg_re,cfg_im,
  input logic [33:0] cfg_lambda,
  output logic cfg_ready,configured,
  input logic s_valid,s_last,
  input logic signed [17:0] s_re,s_im,
  output logic s_ready,
  output logic m_valid,m_last,
  output logic signed [17:0] m_re,m_im,
  input logic m_ready,
  output logic error
);
  localparam int NN=N*N;
  localparam int IW=$clog2(N+1);                     // row / column / pivot counters
  localparam int CW=$clog2(NN+1);                    // configuration entry counter
  localparam int GW=40,AW=34,MW=48,XW=72,ACCW=112,WW=64;
  localparam int F=30,FB=24;
  // floor(log2 N) = clog2(N+1)-1. Positive full-code products need
  // an extra sign bit when N is a power of two.
  localparam int YW=SUM_WIDTH;
  localparam int DEPTH=1<<$clog2(4*N);               // output FIFO, reserves N per tuple
  localparam int FW=$clog2(DEPTH);
  // Independently sized arithmetic; the shared 112-bit divider retains its latency.
  localparam int GAW=GRAM_ACC_WIDTH,UAW=A_PRODUCT_WIDTH,UBW=B_PRODUCT_WIDTH,PBW=ACCW+26;
  initial begin
    if(NORM_WIDTH<70||NORM_WIDTH>138||WEIGHT_WIDTH<87||WEIGHT_WIDTH>138||
       MULT_NUM_WIDTH<65||MULT_NUM_WIDTH>112||BACK_PRODUCT_WIDTH<107||BACK_PRODUCT_WIDTH>112||
       BACK_ACC_WIDTH<106+$clog2(N)||BACK_ACC_WIDTH>112)
      $fatal(1,"[PARAMETER] mmse_n norm/back widths outside proven/legacy range");
    if(A_PRODUCT_WIDTH<83||A_PRODUCT_WIDTH>84||B_PRODUCT_WIDTH<121||B_PRODUCT_WIDTH>122||
       A_UPDATE_WIDTH<53||A_UPDATE_WIDTH>138||B_UPDATE_WIDTH<91||B_UPDATE_WIDTH>138)
      $fatal(1,"[PARAMETER] mmse_n update widths outside proven/legacy range");
    if(N<2||N>8) $fatal(1,"[PARAMETER] mmse_n supports 2 <= N <= 8");
    // max diagonal=(2*N+1)*2^34-1; max imag W*x=2*N*2^80.
    if(GRAM_ACC_WIDTH<36+$clog2(N+1)||GRAM_ACC_WIDTH>44)
      $fatal(1,"[PARAMETER] mmse_n GRAM_ACC_WIDTH outside proven/legacy range");
    if(SUM_WIDTH<82+$clog2(N+1)||SUM_WIDTH>83+$clog2(N))
      $fatal(1,"[PARAMETER] mmse_n SUM_WIDTH outside proven/legacy range");
  end

  wire reset_now=rst==RESET_ACTIVE;
  logic signed [17:0] hr[0:NN-1],hi[0:NN-1];
  logic [33:0] lambda;
  logic [CW-1:0] count;
  typedef enum logic [3:0] {C_IDLE,C_GRAM,C_SCALE,C_NORM,C_PIVOT,C_MULT,C_UPD_A,C_UPD_B,
                            C_BACK,C_SOLVE,C_WEIGHT} cstate_t;
  cstate_t cstate;
  logic [IW-1:0] ci,cj,ck,cc;                       // row, column, pivot, inner index
  logic signed [GW-1:0] gr[0:NN-1],gi[0:NN-1];
  logic signed [AW-1:0] ar[0:NN-1],ai[0:NN-1];
  logic signed [XW-1:0] br[0:NN-1],bi[0:NN-1];
  logic signed [MW-1:0] mr[0:N-1],mi[0:N-1];
  logic signed [WW-1:0] wr[0:NN-1],wi[0:NN-1];
  logic [AW-1:0] dk[0:N-1];                         // positive pivots
  logic signed [GAW-1:0] sum_re,sum_im;
  logic signed [BACK_ACC_WIDTH-1:0] acc_re,acc_im;
  logic [GW-1:0] dmax;
  logic signed [6:0] escale;                        // e = bit_length(dmax) - 31, -30..8
  // Shared divider: numerator re (phase 0) then im (phase 1), denominator d_k.
  logic div_start,div_wait,div_phase;
  logic signed [ACCW-1:0] div_num,quot_re;
  wire div_busy,div_done;
  wire signed [ACCW-1:0] div_result;
  fxp_divide_seq #(.NUM_WIDTH(ACCW),.DEN_WIDTH(AW),.RESET_ACTIVE(RESET_ACTIVE)) divider(
    .clk(clk),.rst(rst),.start(div_start),.numerator(div_num),.denominator(dk[int'(ck)]),
    .busy(div_busy),.done(div_done),.result(div_result));

  function automatic int at(input logic [IW-1:0] row,col);
    return N*int'(row)+int'(col);
  endfunction
  // Round in the product's own context, then narrow before the subtraction.
  // The extra bit also makes each helper exact for its full input-code range.
  function automatic logic signed [UAW:0] round_a_product(input logic signed [UAW-1:0] value);
    return ((UAW+1)'(value)+((UAW+1)'(1)<<<29))>>>30;
  endfunction
  function automatic logic signed [UBW:0] round_b_product(input logic signed [UBW-1:0] value);
    return ((UBW+1)'(value)+((UBW+1)'(1)<<<29))>>>30;
  endfunction
  // Independent full-code headroom: G40 << 30 needs70, X72 << 15 needs87.
  // Positive shifts include the half-up add before shifting; zero is identity.
  function automatic logic signed [NORM_WIDTH-1:0] norm_shift(input logic signed [GW-1:0] value,input int amount);
    if(amount>0) return (NORM_WIDTH'(value)+(NORM_WIDTH'(1)<<<(amount-1)))>>>amount;
    return NORM_WIDTH'(value)<<<(-amount);
  endfunction
  function automatic logic signed [WEIGHT_WIDTH-1:0] weight_shift(input logic signed [XW-1:0] value,input int amount);
    if(amount>0) return (WEIGHT_WIDTH'(value)+(WEIGHT_WIDTH'(1)<<<(amount-1)))>>>amount;
    return WEIGHT_WIDTH'(value)<<<(-amount);
  endfunction
  function automatic bit fits(input logic signed [PBW-1:0] value,input int bits);
    logic signed [PBW-1:0] limit;
    limit=PBW'(1)<<<(bits-1);
    return value>=-limit&&value<limit;
  endfunction
  function automatic logic signed [17:0] sat18(input logic signed [YW-1:0] value);
    logic signed [YW:0] rounded;
    rounded=((YW+1)'(value)+((YW+1)'(1)<<<23))>>>24;
    if(rounded>(YW+1)'(131071)) return 18'sd131071;
    if(rounded<-((YW+1)'(131072))) return 18'sh20000;
    return rounded[17:0];
  endfunction

  // Configuration datapath (combinational, one complex operation per clock).
  // C_GRAM: conj(H[cc][ci]) * H[cc][cj].
  wire signed [GAW-1:0] gram_re=GAW'(hr[at(cc,ci)])*GAW'(hr[at(cc,cj)])+GAW'(hi[at(cc,ci)])*GAW'(hi[at(cc,cj)]);
  wire signed [GAW-1:0] gram_im=GAW'(hr[at(cc,ci)])*GAW'(hi[at(cc,cj)])-GAW'(hi[at(cc,ci)])*GAW'(hr[at(cc,cj)]);
  wire signed [GAW-1:0] gram_next_re=sum_re+gram_re+((cc==IW'(N-1)&&ci==cj)?GAW'($signed({1'b0,lambda})):'0);
  wire signed [GAW-1:0] gram_next_im=sum_im+gram_im;
  // C_NORM: A = round(G, e).
  wire signed [NORM_WIDTH-1:0] norm_re=norm_shift(gr[at(ci,cj)],int'(escale));
  wire signed [NORM_WIDTH-1:0] norm_im=norm_shift(gi[at(ci,cj)],int'(escale));
  // C_MULT numerators: conj(A[ck][ci]) << 30.
  wire signed [MULT_NUM_WIDTH-1:0] mult_num_re=MULT_NUM_WIDTH'(ar[at(ck,ci)])<<<F;
  wire signed [MULT_NUM_WIDTH-1:0] mult_num_im=-(MULT_NUM_WIDTH'(ai[at(ck,ci)])<<<F);
  // C_UPD_A: A[ci][cj] - round(m[ci]*A[ck][cj], 30).
  wire signed [UAW-1:0] ua_re=UAW'(mr[int'(ci)])*UAW'(ar[at(ck,cj)])-UAW'(mi[int'(ci)])*UAW'(ai[at(ck,cj)]);
  wire signed [UAW-1:0] ua_im=UAW'(mr[int'(ci)])*UAW'(ai[at(ck,cj)])+UAW'(mi[int'(ci)])*UAW'(ar[at(ck,cj)]);
  wire signed [A_UPDATE_WIDTH-1:0] upd_a_re=A_UPDATE_WIDTH'(ar[at(ci,cj)])-A_UPDATE_WIDTH'(round_a_product(ua_re));
  wire signed [A_UPDATE_WIDTH-1:0] upd_a_im=A_UPDATE_WIDTH'(ai[at(ci,cj)])-A_UPDATE_WIDTH'(round_a_product(ua_im));
  // C_UPD_B: B[ci][cj] - round(m[ci]*B[ck][cj], 30).
  wire signed [UBW-1:0] ub_re=UBW'(mr[int'(ci)])*UBW'(br[at(ck,cj)])-UBW'(mi[int'(ci)])*UBW'(bi[at(ck,cj)]);
  wire signed [UBW-1:0] ub_im=UBW'(mr[int'(ci)])*UBW'(bi[at(ck,cj)])+UBW'(mi[int'(ci)])*UBW'(br[at(ck,cj)]);
  wire signed [B_UPDATE_WIDTH-1:0] upd_b_re=B_UPDATE_WIDTH'(br[at(ci,cj)])-B_UPDATE_WIDTH'(round_b_product(ub_re));
  wire signed [B_UPDATE_WIDTH-1:0] upd_b_im=B_UPDATE_WIDTH'(bi[at(ci,cj)])-B_UPDATE_WIDTH'(round_b_product(ub_im));
  // C_BACK: acc - A[ck][cc]*X[cc][cj]; C_SOLVE: X = acc / d_k.
  // Imaginary product reaches +2^105 at the two negative rails:107 bits.
  wire signed [BACK_PRODUCT_WIDTH-1:0] back_product_re=BACK_PRODUCT_WIDTH'(ar[at(ck,cc)])*BACK_PRODUCT_WIDTH'(br[at(cc,cj)])-BACK_PRODUCT_WIDTH'(ai[at(ck,cc)])*BACK_PRODUCT_WIDTH'(bi[at(cc,cj)]);
  wire signed [BACK_PRODUCT_WIDTH-1:0] back_product_im=BACK_PRODUCT_WIDTH'(ar[at(ck,cc)])*BACK_PRODUCT_WIDTH'(bi[at(cc,cj)])+BACK_PRODUCT_WIDTH'(ai[at(ck,cc)])*BACK_PRODUCT_WIDTH'(br[at(cc,cj)]);
  // At most N-1 terms: min acc=-2^101-(N-1)*2^105, including every prefix.
  wire signed [BACK_ACC_WIDTH-1:0] back_re=acc_re-BACK_ACC_WIDTH'(back_product_re);
  wire signed [BACK_ACC_WIDTH-1:0] back_im=acc_im-BACK_ACC_WIDTH'(back_product_im);
  // C_WEIGHT: W = round(X, e + 15).
  wire signed [WEIGHT_WIDTH-1:0] weight_re=weight_shift(br[at(ci,cj)],int'(escale)+15);
  wire signed [WEIGHT_WIDTH-1:0] weight_im=weight_shift(bi[at(ci,cj)],int'(escale)+15);
  logic [5:0] dbits;
  always_comb begin
    dbits='0;
    for(int b=0;b<GW;b++) if(dmax[b]) dbits=6'(b+1);
  end

  // Observation datapath.
  logic [IW-1:0] index;
  logic frame_active;
  logic [FW:0] fifo_count;
  logic [IW:0] pending;
  logic [FW-1:0] fifo_head,fifo_tail;
  logic [36:0] fifo[0:DEPTH-1];
  logic p_valid,p_last,e_valid,e_last;
  logic signed [YW-1:0] yr[0:N-1],yi[0:N-1];
  logic signed [17:0] er[0:N-1],ei[0:N-1];
  assign cfg_ready=!reset_now&&!error&&cstate==C_IDLE&&!frame_active&&index==0
                   &&fifo_count==0&&pending==0&&!p_valid&&!e_valid;
  wire cfg_take=cfg_valid&&cfg_ready;
  wire [FW+IW+1:0] occupied=(FW+IW+2)'(fifo_count)+(FW+IW+2)'(pending)*(FW+IW+2)'(N);
  assign s_ready=!reset_now&&!error&&configured&&cstate==C_IDLE&&count==0
                 &&!cfg_take&&(index!=0||occupied<=(FW+IW+2)'(DEPTH-N));
  wire take=s_valid&&s_ready;
  wire pop=m_valid&&m_ready;
  wire abort_partial=take&&s_last&&index!=IW'(N-1);
  wire reserve=take&&index==0&&!abort_partial;
  wire cancel=abort_partial&&index!=0;
  assign m_valid=fifo_count!=0;
  assign m_re=fifo[fifo_head][36:19];assign m_im=fifo[fifo_head][18:1];assign m_last=fifo[fifo_head][0];

  task automatic fail;
    error<=1;configured<=0;cstate<=C_IDLE;
  endtask

  always_ff @(posedge clk) begin
    if(reset_now) begin
      configured<=0;error<=0;count<='0;cstate<=C_IDLE;div_start<=0;div_wait<=0;div_phase<=0;
      ci<='0;cj<='0;ck<='0;cc<='0;
      index<='0;frame_active<=0;p_valid<=0;e_valid<=0;
      pending<='0;fifo_count<='0;fifo_head<='0;fifo_tail<='0;
    end else begin
      div_start<=0;
      if(cfg_take) begin
        configured<=0;
        if(count<CW'(NN)) begin hr[int'(count)]<=cfg_re;hi[int'(count)]<=cfg_im;count<=count+1'b1;end
        else begin count<=CW'(NN);error<=1;end
        if(cfg_last) begin
          count<='0;lambda<=cfg_lambda;
          ci<='0;cj<='0;cc<='0;sum_re<='0;sum_im<='0;dmax<='0;
          if(count==CW'(NN-1)) cstate<=C_GRAM;
          else error<=1;
        end
      end
      case(cstate)
        C_IDLE: begin end
        C_GRAM: begin
          // Upper triangle only; G[ci][cj] = sum over cc, lambda on the diagonal.
          if(cc==IW'(N-1)) begin
            if(!fits(PBW'(gram_next_re),GW)||!fits(PBW'(gram_next_im),GW)) fail();
            else begin
              gr[at(ci,cj)]<=GW'(gram_next_re);gi[at(ci,cj)]<=GW'(gram_next_im);
              if(ci==cj&&$unsigned(GW'(gram_next_re))>dmax&&!gram_next_re[GAW-1]) dmax<=GW'(gram_next_re);
              sum_re<='0;sum_im<='0;cc<='0;
              if(cj==IW'(N-1)) begin
                if(ci==IW'(N-1)) cstate<=C_SCALE;
                else begin ci<=ci+1'b1;cj<=ci+1'b1;end
              end else cj<=cj+1'b1;
            end
          end else begin
            sum_re<=gram_next_re;sum_im<=gram_next_im;cc<=cc+1'b1;
          end
        end
        C_SCALE: begin
          if(dmax==0) fail();
          else begin escale<=7'(int'(dbits)-31);ci<='0;cj<='0;cstate<=C_NORM;end
        end
        C_NORM: begin
          // B = H^H << 24 for every entry; A = round(G, e) on the upper triangle.
          br[at(ci,cj)]<=XW'(hr[at(cj,ci)])<<<FB;bi[at(ci,cj)]<=-(XW'(hi[at(cj,ci)])<<<FB);
          if(cj>=ci&&(!fits(PBW'(norm_re),AW)||!fits(PBW'(norm_im),AW))) fail();
          else begin
            if(cj>=ci) begin ar[at(ci,cj)]<=AW'(norm_re);ai[at(ci,cj)]<=AW'(norm_im);end
            if(cj==IW'(N-1)) begin
              cj<='0;
              if(ci==IW'(N-1)) begin ck<='0;cstate<=C_PIVOT;end
              else ci<=ci+1'b1;
            end else cj<=cj+1'b1;
          end
        end
        C_PIVOT: begin
          if(ar[at(ck,ck)]<=0||ai[at(ck,ck)]!=0) fail();
          else begin
            dk[int'(ck)]<=AW'(ar[at(ck,ck)]);
            if(ck==IW'(N-1)) begin cj<='0;cc<=IW'(N);acc_re<=BACK_ACC_WIDTH'(br[at(ck,0)])<<<F;acc_im<=BACK_ACC_WIDTH'(bi[at(ck,0)])<<<F;cstate<=C_BACK;end
            else begin ci<=ck+1'b1;cstate<=C_MULT;end
          end
        end
        C_MULT: begin
          if(!div_wait&&!div_busy) begin div_num<=div_phase?ACCW'(mult_num_im):ACCW'(mult_num_re);div_start<=1;div_wait<=1;end
          else if(div_done) begin
            div_wait<=0;div_phase<=!div_phase;
            if(!div_phase) quot_re<=div_result;
            else if(!fits(PBW'(quot_re),MW)||!fits(PBW'(div_result),MW)) fail();
            else begin
              mr[int'(ci)]<=MW'(quot_re);mi[int'(ci)]<=MW'(div_result);
              if(ci==IW'(N-1)) begin ci<=ck+1'b1;cj<=ck+1'b1;cstate<=C_UPD_A;end
              else ci<=ci+1'b1;
            end
          end
        end
        C_UPD_A: begin
          if(!fits(PBW'(upd_a_re),AW)||(ci!=cj&&!fits(PBW'(upd_a_im),AW))) fail();
          else begin
            ar[at(ci,cj)]<=AW'(upd_a_re);ai[at(ci,cj)]<=ci==cj?'0:AW'(upd_a_im);
            if(cj==IW'(N-1)) begin
              if(ci==IW'(N-1)) begin ci<=ck+1'b1;cj<='0;cstate<=C_UPD_B;end
              else begin ci<=ci+1'b1;cj<=ci+1'b1;end
            end else cj<=cj+1'b1;
          end
        end
        C_UPD_B: begin
          if(!fits(PBW'(upd_b_re),XW)||!fits(PBW'(upd_b_im),XW)) fail();
          else begin
            br[at(ci,cj)]<=XW'(upd_b_re);bi[at(ci,cj)]<=XW'(upd_b_im);
            if(cj==IW'(N-1)) begin
              cj<='0;
              if(ci==IW'(N-1)) begin ck<=ck+1'b1;cstate<=C_PIVOT;end
              else ci<=ci+1'b1;
            end else cj<=cj+1'b1;
          end
        end
        C_BACK: begin
          // acc already holds B[ck][cj] << 30; subtract A[ck][cc]*X[cc][cj] for cc > ck.
          if(cc>=IW'(N)) cstate<=C_SOLVE;
          // Consume/check the complete product before any accumulator-width cast.
          // Proven true for all stored codes; also covers mixed legacy widths.
          else if(!fits(PBW'(back_product_re),BACK_ACC_WIDTH)||!fits(PBW'(back_product_im),BACK_ACC_WIDTH)) fail();
          else begin acc_re<=back_re;acc_im<=back_im;cc<=cc+1'b1;end
        end
        C_SOLVE: if(!div_wait&&!div_busy) begin
          div_num<=div_phase?ACCW'(acc_im):ACCW'(acc_re);div_start<=1;div_wait<=1;
        end else if(div_done) begin
          div_wait<=0;div_phase<=!div_phase;
          if(!div_phase) quot_re<=div_result;
          else if(!fits(PBW'(quot_re),XW)||!fits(PBW'(div_result),XW)) fail();
          else begin
            br[at(ck,cj)]<=XW'(quot_re);bi[at(ck,cj)]<=XW'(div_result);
            if(cj==IW'(N-1)) begin
              if(ck==0) begin ci<='0;cj<='0;cstate<=C_WEIGHT;end
              else begin
                ck<=ck-1'b1;cj<='0;cc<=ck;cstate<=C_BACK;
                acc_re<=BACK_ACC_WIDTH'(br[at(ck-1'b1,0)])<<<F;acc_im<=BACK_ACC_WIDTH'(bi[at(ck-1'b1,0)])<<<F;
              end
            end else begin
              cj<=cj+1'b1;cc<=ck+1'b1;cstate<=C_BACK;
              acc_re<=BACK_ACC_WIDTH'(br[at(ck,cj+1'b1)])<<<F;acc_im<=BACK_ACC_WIDTH'(bi[at(ck,cj+1'b1)])<<<F;
            end
          end
        end
        C_WEIGHT: begin
          if(!fits(PBW'(weight_re),WW)||!fits(PBW'(weight_im),WW)) fail();
          else begin
            wr[at(ci,cj)]<=WW'(weight_re);wi[at(ci,cj)]<=WW'(weight_im);
            if(cj==IW'(N-1)) begin
              cj<='0;
              if(ci==IW'(N-1)) begin configured<=1;cstate<=C_IDLE;end
              else ci<=ci+1'b1;
            end else cj<=cj+1'b1;
          end
        end
        default: fail();
      endcase
      p_valid<=take&&index==IW'(N-1);e_valid<=p_valid;
      if(take) begin
        frame_active<=!s_last;
        if(abort_partial) begin error<=1;configured<=0;index<='0;end
        else begin
          index<=index==IW'(N-1)?'0:index+1'b1;
          if(index==IW'(N-1)) p_last<=s_last;
          for(int row=0;row<N;row++) begin
            yr[row]<=(index==0?'0:yr[row])+YW'(wr[N*row+int'(index)])*YW'(s_re)-YW'(wi[N*row+int'(index)])*YW'(s_im);
            yi[row]<=(index==0?'0:yi[row])+YW'(wr[N*row+int'(index)])*YW'(s_im)+YW'(wi[N*row+int'(index)])*YW'(s_re);
          end
        end
      end
      for(int row=0;row<N;row++) begin er[row]<=sat18(yr[row]);ei[row]<=sat18(yi[row]);end
      e_last<=p_last;
      if(e_valid) begin
        for(int row=0;row<N;row++)
          fifo[fifo_tail+FW'(row)]<={er[row],ei[row],row==N-1?e_last:1'b0};
        fifo_tail<=FW'(int'(fifo_tail)+N);
      end
      if(pop) fifo_head<=fifo_head+1'b1;
      fifo_count<=fifo_count+(FW+1)'(N*int'(e_valid))-(FW+1)'(pop);
      pending<=pending+(IW+1)'(reserve)-(IW+1)'(e_valid)-(IW+1)'(cancel);
    end
  end
endmodule
