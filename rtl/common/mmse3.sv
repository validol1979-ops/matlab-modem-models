// Exact integer 3x3 MMSE/ZF: H Q15 -> G Q30 -> adj(G) Q60 ->
// det Q90 -> M Q75 -> W Q24. Configuration performs one matrix entry per clock;
// division is sequential. This source makes no physical timing claim.
// cfg_last belongs to H22 (ninth coefficient); lambda is unsigned Q30 there.
// Frames contain complete observation triples; only the third sample may carry
// s_last. Configuration errors and early s_last are sticky until reset.
module mmse3 #(
  parameter bit RESET_ACTIVE=1,
  parameter int GRAM_WIDTH=38,
  parameter int SUM_WIDTH=84,
  parameter int ADJ_WIDTH=81,
  parameter int DET_WIDTH=126,
  parameter int M_WIDTH=104,
  parameter int SCALE_WIDTH=145
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
  localparam int GW=40,AW=84,DW=128,MW=106,WW=64,PW=SCALE_WIDTH,YW=SUM_WIDTH;
  initial begin
    // For positive signed128 det, norm gives r<=2^23 and shift=8..134.
    // Full signed106 M times r, then at most <<16, fits signed145 exactly.
    if(SCALE_WIDTH<145||SCALE_WIDTH>156)
      $fatal(1,"[PARAMETER] MMSE3 SCALE_WIDTH must be 145..156");
    if(GRAM_WIDTH<38||GRAM_WIDTH>40)
      $fatal(1,"[PARAMETER] MMSE3 GRAM_WIDTH must be 38..40");
    if(SUM_WIDTH<84||SUM_WIDTH>85)
      $fatal(1,"[PARAMETER] MMSE3 SUM_WIDTH must be 84..85");
    if(ADJ_WIDTH<81||ADJ_WIDTH>84)
      $fatal(1,"[PARAMETER] MMSE3 ADJ_WIDTH must be 81..84");
    if(DET_WIDTH<126||DET_WIDTH>128)
      $fatal(1,"[PARAMETER] MMSE3 DET_WIDTH must be 126..128");
    if(M_WIDTH<104||M_WIDTH>106)
      $fatal(1,"[PARAMETER] MMSE3 M_WIDTH must be 104..106");
  end
  wire reset_now=rst==RESET_ACTIVE;
  logic signed [17:0] hr[0:8],hi[0:8];
  logic [33:0] lambda;
  logic [3:0] count,entry;
  typedef enum logic [2:0] {C_IDLE,C_GRAM,C_ADJ,C_DET,C_RECIP,C_M,C_WEIGHT} cstate_t;
  cstate_t cstate;
  logic signed [GW-1:0] gr[0:8],gi[0:8];
  logic signed [AW-1:0] ar[0:8],ai[0:8];
  logic signed [DW-1:0] det;
  logic signed [MW-1:0] mr[0:8],mi[0:8];
  logic signed [WW-1:0] wr[0:8],wi[0:8];
  logic norm_start,norm_done,norm_zero;
  logic [23:0] r;
  logic [7:0] shift;
  norm_reciprocal #(.WIDTH(DW),.SHIFT_WIDTH(8),.RESET_ACTIVE(RESET_ACTIVE)) norm(
    .clk(clk),.rst(rst),.start(norm_start),.energy(DW'(det)),
    .done(norm_done),.zero(norm_zero),.r(r),.shift(shift));

  function automatic logic signed [GRAM_WIDTH-1:0] gram(input int row,col,input bit imag_part);
    logic signed [GRAM_WIDTH-1:0] total;
    total='0;
    for(int k=0;k<3;k++) begin
      if(imag_part) total+=GRAM_WIDTH'(hr[3*k+row])*GRAM_WIDTH'(hi[3*k+col])-GRAM_WIDTH'(hi[3*k+row])*GRAM_WIDTH'(hr[3*k+col]);
      else total+=GRAM_WIDTH'(hr[3*k+row])*GRAM_WIDTH'(hr[3*k+col])+GRAM_WIDTH'(hi[3*k+row])*GRAM_WIDTH'(hi[3*k+col]);
    end
    if(!imag_part&&row==col) total+=GRAM_WIDTH'($signed({1'b0,lambda}));
    return total;
  endfunction
  // Arithmetic widths cover all independent signed codes of the stored operands:
  // balanced +/- four G40*G40 terms, six G40*A84 terms, six A84*H18 terms.
  // Cofactors attain +/- (2^80-2^40), including odd-parity negation.
  // Function return types isolate evaluation from the wider destination registers.
  function automatic logic signed [ADJ_WIDTH-1:0] adjugate(input int row,col,input bit imag_part);
    int ra,rb,ca,cb;
    logic signed [ADJ_WIDTH-1:0] total;
    // adj[row,col] is cofactor[col,row]: remove row col and column row.
    ra=col==0?1:0;rb=col==2?1:2;ca=row==0?1:0;cb=row==2?1:2;
    if(imag_part)
      total=ADJ_WIDTH'(gr[3*ra+ca])*ADJ_WIDTH'(gi[3*rb+cb])+ADJ_WIDTH'(gi[3*ra+ca])*ADJ_WIDTH'(gr[3*rb+cb])
           -ADJ_WIDTH'(gr[3*ra+cb])*ADJ_WIDTH'(gi[3*rb+ca])-ADJ_WIDTH'(gi[3*ra+cb])*ADJ_WIDTH'(gr[3*rb+ca]);
    else
      total=ADJ_WIDTH'(gr[3*ra+ca])*ADJ_WIDTH'(gr[3*rb+cb])-ADJ_WIDTH'(gi[3*ra+ca])*ADJ_WIDTH'(gi[3*rb+cb])
           -ADJ_WIDTH'(gr[3*ra+cb])*ADJ_WIDTH'(gr[3*rb+ca])+ADJ_WIDTH'(gi[3*ra+cb])*ADJ_WIDTH'(gi[3*rb+ca]);
    if(((row+col)&1)!=0) total=-total;
    return total;
  endfunction
  function automatic logic signed [DET_WIDTH-1:0] determinant(input bit imag_part);
    logic signed [DET_WIDTH-1:0] total;
    total='0;
    for(int k=0;k<3;k++) begin
      if(imag_part) total+=DET_WIDTH'(gr[k])*DET_WIDTH'(ai[3*k])+DET_WIDTH'(gi[k])*DET_WIDTH'(ar[3*k]);
      else total+=DET_WIDTH'(gr[k])*DET_WIDTH'(ar[3*k])-DET_WIDTH'(gi[k])*DET_WIDTH'(ai[3*k]);
    end
    return total;
  endfunction
  function automatic logic signed [M_WIDTH-1:0] mentry(input int row,col,input bit imag_part);
    logic signed [M_WIDTH-1:0] total;
    total='0;
    for(int k=0;k<3;k++) begin
      if(imag_part) total+=M_WIDTH'(ai[3*row+k])*M_WIDTH'(hr[3*col+k])-M_WIDTH'(ar[3*row+k])*M_WIDTH'(hi[3*col+k]);
      else total+=M_WIDTH'(ar[3*row+k])*M_WIDTH'(hr[3*col+k])+M_WIDTH'(ai[3*row+k])*M_WIDTH'(hi[3*col+k]);
    end
    return total;
  endfunction
  function automatic logic signed [PW-1:0] scale_product(input logic signed [MW-1:0] value);
    return PW'(value)*PW'($signed({1'b0,r}));
  endfunction
  function automatic logic signed [PW-1:0] wround(input logic signed [MW-1:0] value);
    logic signed [PW-1:0] product;
    int amount;
    product=scale_product(value);
    amount=int'(shift)-24; // norm shift=Z-15, so this is Z-39.
    if(amount>0) return (product+(PW'(1)<<<(amount-1)))>>>amount;
    if(amount==0) return product;
    return product<<<(-amount); // det>=1 implies amount>=-16; PW keeps the headroom.
  endfunction
  function automatic bit coefficient_overflow(input logic signed [PW-1:0] value);
    return value[PW-1:WW-1]!={(PW-WW+1){value[WW-1]}};
  endfunction
  function automatic logic signed [17:0] sat18(input logic signed [YW-1:0] value);
    logic signed [YW:0] rounded;
    rounded=((YW+1)'(value)+((YW+1)'(1)<<<23))>>>24;
    if(rounded>(YW+1)'(131071)) return 18'sd131071;
    if(rounded<-((YW+1)'(131072))) return 18'sh20000;
    return rounded[17:0];
  endfunction

  logic [1:0] index;
  logic signed [17:0] obs_re[0:1],obs_im[0:1];
  logic frame_active;
  logic [4:0] fifo_count,pending;
  logic [3:0] fifo_head,fifo_tail;
  logic [36:0] fifo[0:15];
  logic p_valid,p_last,e_valid,e_last;
  logic signed [YW-1:0] yr[0:2],yi[0:2];
  logic signed [17:0] er[0:2],ei[0:2];
  assign cfg_ready=!reset_now&&!error&&cstate==C_IDLE&&!frame_active&&index==0
                   &&fifo_count==0&&pending==0&&!p_valid&&!e_valid;
  wire cfg_take=cfg_valid&&cfg_ready;
  wire [6:0] occupied=7'(fifo_count)+7'(pending)*7'd3;
  assign s_ready=!reset_now&&!error&&configured&&cstate==C_IDLE&&count==0
                 &&!cfg_take&&(index!=0||occupied<=7'd13);
  wire take=s_valid&&s_ready;
  wire pop=m_valid&&m_ready;
  wire abort_partial=take&&s_last&&index!=2;
  wire reserve=take&&index==0&&!abort_partial;
  wire cancel=abort_partial&&index!=0;
  assign m_valid=fifo_count!=0;
  assign m_re=fifo[fifo_head][36:19];assign m_im=fifo[fifo_head][18:1];assign m_last=fifo[fifo_head][0];

  always_ff @(posedge clk) begin
    if(reset_now) begin
      configured<=0;error<=0;count<='0;entry<='0;cstate<=C_IDLE;norm_start<=0;
      index<='0;frame_active<=0;p_valid<=0;e_valid<=0;
      pending<='0;fifo_count<='0;fifo_head<='0;fifo_tail<='0;
    end else begin
      norm_start<=0;
      if(cfg_take) begin
        configured<=0;
        if(count<4'd9) begin hr[count]<=cfg_re;hi[count]<=cfg_im;count<=count+1'b1;end
        else begin count<=4'd9;error<=1;end
        if(cfg_last) begin
          count<='0;lambda<=cfg_lambda;entry<='0;
          if(count==4'd8) cstate<=C_GRAM;
          else error<=1;
        end
      end
      case(cstate)
        C_IDLE: begin end
        C_GRAM: begin
          gr[entry]<=GW'(gram(int'(entry)/3,int'(entry)%3,0));
          gi[entry]<=GW'(gram(int'(entry)/3,int'(entry)%3,1));
          if(entry==4'd8) begin entry<='0;cstate<=C_ADJ;end
          else entry<=entry+1'b1;
        end
        C_ADJ: begin
          ar[entry]<=AW'(adjugate(int'(entry)/3,int'(entry)%3,0));
          ai[entry]<=AW'(adjugate(int'(entry)/3,int'(entry)%3,1));
          if(entry==4'd8) begin entry<='0;cstate<=C_DET;end
          else entry<=entry+1'b1;
        end
        C_DET: begin
          det<=DW'(determinant(0));
          if(determinant(0)<=0||determinant(1)!=0) begin error<=1;cstate<=C_IDLE;end
          else begin norm_start<=1;cstate<=C_RECIP;end
        end
        C_RECIP: if(!norm_start) begin
          if(norm_zero) begin error<=1;cstate<=C_IDLE;end
          else if(norm_done) begin entry<='0;cstate<=C_M;end
        end
        C_M: begin
          mr[entry]<=MW'(mentry(int'(entry)/3,int'(entry)%3,0));
          mi[entry]<=MW'(mentry(int'(entry)/3,int'(entry)%3,1));
          if(entry==4'd8) begin entry<='0;cstate<=C_WEIGHT;end
          else entry<=entry+1'b1;
        end
        C_WEIGHT: begin
          if(coefficient_overflow(wround(mr[entry]))||coefficient_overflow(wround(mi[entry]))) begin
            error<=1;configured<=0;cstate<=C_IDLE;
          end else begin
            wr[entry]<=WW'(wround(mr[entry]));wi[entry]<=WW'(wround(mi[entry]));
            if(entry==4'd8) begin entry<='0;configured<=1;cstate<=C_IDLE;end
            else entry<=entry+1'b1;
          end
        end
        default: begin error<=1;configured<=0;cstate<=C_IDLE;end
      endcase
      p_valid<=take&&index==2;e_valid<=p_valid;
      if(take) begin
        // Track the input frame separately from queued outputs. Empty FIFO and
        // pending/pipeline guards protect configuration; consecutive frames can stream.
        frame_active<=!s_last;
        if(abort_partial) begin error<=1;configured<=0;index<='0;end
        else if(index==2) begin
          index<='0;p_last<=s_last;
          for(int row=0;row<3;row++) begin
            yr[row]<=YW'(wr[3*row])*YW'(obs_re[0])-YW'(wi[3*row])*YW'(obs_im[0])
                    +YW'(wr[3*row+1])*YW'(obs_re[1])-YW'(wi[3*row+1])*YW'(obs_im[1])
                    +YW'(wr[3*row+2])*YW'(s_re)-YW'(wi[3*row+2])*YW'(s_im);
            yi[row]<=YW'(wr[3*row])*YW'(obs_im[0])+YW'(wi[3*row])*YW'(obs_re[0])
                    +YW'(wr[3*row+1])*YW'(obs_im[1])+YW'(wi[3*row+1])*YW'(obs_re[1])
                    +YW'(wr[3*row+2])*YW'(s_im)+YW'(wi[3*row+2])*YW'(s_re);
          end
        end else begin
          obs_re[index[0]]<=s_re;obs_im[index[0]]<=s_im;index<=index+1'b1;
        end
      end
      for(int row=0;row<3;row++) begin er[row]<=sat18(yr[row]);ei[row]<=sat18(yi[row]);end
      e_last<=p_last;
      if(e_valid) begin
        fifo[fifo_tail]<={er[0],ei[0],1'b0};
        fifo[4'(fifo_tail+4'd1)]<={er[1],ei[1],1'b0};
        fifo[4'(fifo_tail+4'd2)]<={er[2],ei[2],e_last};
        fifo_tail<=fifo_tail+4'd3;
      end
      if(pop) begin
        fifo_head<=fifo_head+1'b1;
      end
      fifo_count<=fifo_count+5'(3*int'(e_valid))-5'(pop);
      pending<=pending+5'(reserve)-5'(e_valid)-5'(cancel);
    end
  end
endmodule
