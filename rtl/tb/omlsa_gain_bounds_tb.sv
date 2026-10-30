// Arbitrary operand codes of the narrowed omlsa_gain arithmetic: registers and ROM ports are
// forced (no clocks, no reset-reachability claim) and every raw product, rounding and limiter
// input is compared with a 128-bit reference. UNSAFE_WIDTH_TEST=1 with one width one bit below
// the proven one must fail [ARITHMETIC]; +INJECT_DIRECTED corrupts one observation.
`timescale 1ns/1ps
module omlsa_gain_bounds_tb;
  parameter int LOG2N=4,RECIP_WIDTH=18,GAMMA_WIDTH=72,XI_WIDTH=47,V_WIDTH=48,G1_WIDTH=37,T_WIDTH=48,A_WIDTH=37,OUT_WIDTH=41,GG_WIDTH=34,PREV_WIDTH=49;
  parameter bit RESET_ACTIVE=1,UNSAFE_WIDTH_TEST=0;
  parameter string MEM_DIR="rtl/common/mem/";
  localparam logic [127:0] GMAX=128'h7fffffff;
  logic clk=0,rst=RESET_ACTIVE;
  logic [16:0] alpha=0,recip_q=0,p=0,g=0,w=0;
  logic [48:0] power=0;
  logic [23:0] rn=0;
  logic [6:0] zn=0;
  logic [5:0] rs=17;
  logic [30:0] prev=0,gamma=0,xi=0;
  logic [19:0] tf_q=0;
  logic [15:0] te_q=0;
  logic [18:0] ln_q=0;
  logic signed [23:0] re=0,im=0;
  int checks[0:9];
  omlsa_gain #(.LOG2N(LOG2N),.RESET_ACTIVE(RESET_ACTIVE),.MEM_DIR(MEM_DIR),.RECIP_WIDTH(RECIP_WIDTH),.GAMMA_WIDTH(GAMMA_WIDTH),
      .XI_WIDTH(XI_WIDTH),.V_WIDTH(V_WIDTH),.G1_WIDTH(G1_WIDTH),.T_WIDTH(T_WIDTH),.A_WIDTH(A_WIDTH),.OUT_WIDTH(OUT_WIDTH),
      .GG_WIDTH(GG_WIDTH),.PREV_WIDTH(PREV_WIDTH),.UNSAFE_WIDTH_TEST(UNSAFE_WIDTH_TEST)) dut
    (.clk(clk),.rst(rst),.nnoise(5'd1),.alpha(alpha),.s_valid(1'b0),.s_last(1'b0),.s_re(24'sd0),.s_im(24'sd0),.s_ready(),
     .m_valid(),.m_last(),.m_re(),.m_im(),.m_ready(1'b1),.error());
  initial begin
    force dut.k='0;force dut.power=power;force dut.rn[0]=rn;force dut.zn[0]=zn;force dut.prev[0]=prev;
    force dut.gamma=gamma;force dut.xi=xi;force dut.w=w;force dut.p=p;force dut.g=g;force dut.re=re;force dut.im=im;
    force dut.rs=rs;force dut.recip_q=recip_q;force dut.tf_q=tf_q;force dut.te_q=te_q;force dut.ln_q=ln_q;
  end
  function automatic logic [127:0] rnd(input logic [127:0] v,input int s);return s==0 ? v : (v+(128'd1<<(s-1)))>>s;endfunction
  function automatic logic signed [127:0] srnd(input logic signed [127:0] v);return (v+(128'sd1<<<15))>>>16;endfunction
  function automatic logic [127:0] cap(input logic [127:0] v);return v>GMAX ? GMAX : v;endfunction
  task automatic expect_equal(input int stage,input logic [127:0] observed,input logic [127:0] expected,input string what);
    if(stage==0&&checks[0]==0&&$test$plusargs("INJECT_DIRECTED"))observed++;
    if(observed!==expected)$fatal(1,"[ARITHMETIC] OM-LSA %s corner: %0d != %0d",what,observed,expected);
    checks[stage]++;
  endtask
  initial begin
    logic [127:0] raw,rounded,excess;
    logic signed [127:0] sraw,sround;
    logic [6:0] shift;
    logic [16:0] q17[5]='{17'd0,17'd1,17'd65535,17'd65536,17'h1ffff};
    logic [48:0] powers[5]='{49'd0,49'd1,49'd1<<46,(49'd1<<47)-1,49'd1<<47};
    logic [23:0] rns[5]='{24'd0,24'd1,24'd4194304,24'd8388608,24'hffffff};
    logic [30:0] g31[4]='{31'd0,31'd1,31'd65537,31'h7fffffff};
    logic [16:0] alphas[5]='{17'd0,17'd1,17'd32768,17'd65535,17'd65536};
    logic [18:0] lns[5]='{19'h40000,19'd0,19'h3ffff,19'(-196328),19'd8};
    logic signed [23:0] samples[4]='{-24'sd8388608,24'sd8388607,24'sd0,-24'sd1};
    for(int k=0;k<10;k++)checks[k]=0;
    #1;
    // R(u): every 6-bit rs code (shift 7'(rs) - 17, i.e. 0..46 and 111..127).
    foreach(q17[i])for(int r=0;r<64;r++)begin
      recip_q=q17[i];rs=6'(r);#1;shift=7'(rs)-7'd17;rounded=rnd(128'(recip_q),int'(shift));
      expect_equal(0,128'(dut.recip_round),rounded,"reciprocal");
      expect_equal(0,128'(dut.recip_value),rs==6'd17 ? 128'(recip_q) : 128'(17'(rounded)),"reciprocal value");
    end
    // gamma: every 7-bit zn code (shift zn - 1, 0..127).
    foreach(powers[i])foreach(rns[j])for(int z=0;z<128;z++)begin
      power=powers[i];rn=rns[j];zn=7'(z);#1;raw=128'(power)*128'(rn);shift=zn-1'b1;
      expect_equal(1,128'(dut.gamma_raw),raw,"gamma product");expect_equal(1,128'(dut.gamma_round),rnd(raw,int'(shift)),"gamma round");
    end
    foreach(alphas[i])foreach(g31[j])foreach(g31[m])begin
      alpha=alphas[i];prev=g31[j];gamma=g31[m];#1;
      excess=gamma>31'd65536 ? 128'(gamma)-128'd65536 : 128'd0;raw=128'(alpha)*128'(prev)+(128'd65536-128'(alpha))*excess;rounded=rnd(raw,16);
      expect_equal(2,128'(dut.xi_raw),raw,"xi product");expect_equal(2,128'(dut.xi_round),rounded,"xi round");
      expect_equal(2,128'(dut.xi_next),cap(rounded),"xi limiter");
    end
    foreach(g31[i])foreach(q17[j])begin
      gamma=g31[i];w=q17[j];#1;raw=128'(gamma)*128'(w);
      expect_equal(3,128'(dut.v_raw),raw,"v product");expect_equal(3,128'(dut.v_round),rnd(raw,16),"v round");
    end
    foreach(q17[i])for(int t=0;t<3;t++)begin
      w=q17[i];tf_q=t==0 ? 20'd0 : t==1 ? 20'd1 : 20'hfffff;#1;raw=128'(w)*128'(tf_q);
      expect_equal(4,128'(dut.g1_raw),raw,"G1 product");expect_equal(4,128'(dut.g1_next),rnd(raw,12),"G1 round");
    end
    foreach(g31[i])for(int t=0;t<3;t++)begin
      xi=g31[i];te_q=t==0 ? 16'd0 : t==1 ? 16'd1 : 16'hffff;#1;raw=(128'd65536+128'(xi))*128'(te_q);
      expect_equal(5,128'(dut.t_raw),raw,"t product");expect_equal(5,128'(dut.t_round),rnd(raw,18),"t round");
    end
    foreach(q17[i])foreach(lns[j])begin
      p=q17[i];ln_q=lns[j];#1;sraw=128'(p)*(128'($signed(ln_q))+128'sd196328);sround=srnd(sraw);
      expect_equal(6,128'(dut.a_raw),sraw,"a product");expect_equal(6,128'(dut.a_round),sround,"a round");
    end
    foreach(samples[i])foreach(samples[j])foreach(q17[m])begin
      re=samples[i];im=samples[j];g=q17[m];#1;
      sraw=128'(re)*128'($signed({1'b0,g}));expect_equal(7,128'(dut.out_raw_re),sraw,"output re product");
      expect_equal(7,128'(dut.out_round_re),srnd(sraw),"output re round");
      sraw=128'(im)*128'($signed({1'b0,g}));expect_equal(7,128'(dut.out_raw_im),sraw,"output im product");
      expect_equal(7,128'(dut.out_round_im),srnd(sraw),"output im round");
    end
    foreach(q17[i])foreach(g31[j])begin
      g=q17[i];gamma=g31[j];#1;raw=128'(g)*128'(g);rounded=rnd(raw,16);
      expect_equal(8,128'(dut.gg_raw),raw,"G^2 product");expect_equal(8,128'(dut.gg_round),rounded,"G^2 round");
      raw=rounded*128'(gamma);expect_equal(9,128'(dut.prev_raw),raw,"prev product");expect_equal(9,128'(dut.prev_round),rnd(raw,16),"prev round");
    end
    $display("PASS OMLSA GAIN BOUNDS: %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d",checks[0],checks[1],checks[2],checks[3],checks[4],
      checks[5],checks[6],checks[7],checks[8],checks[9]);
    $finish;
  end
endmodule
