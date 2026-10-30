// Full stored-code arithmetic tests. Deliberately independent G40/A84/H18
// operands; these overrides make no claim about reachable configurations.
`timescale 1ns/1ps
module mmse3_config_width_tb;
  parameter bit RESET_ACTIVE=1;
  parameter int ADJ_WIDTH=81,DET_WIDTH=126,M_WIDTH=104;
  logic clk=0,rst=!RESET_ACTIVE;
  logic cfg_ready,configured,s_ready,m_valid,m_last,error;
  logic signed [17:0] m_re,m_im;
  logic [3:0] entry_code=0;
  longint checks[0:5];
  logic signed [127:0] extrema_min[0:5],extrema_max[0:5];
  mmse3 #(.RESET_ACTIVE(RESET_ACTIVE),.ADJ_WIDTH(ADJ_WIDTH),.DET_WIDTH(DET_WIDTH),.M_WIDTH(M_WIDTH)) dut(
    .clk(clk),.rst(rst),.cfg_valid(1'b0),.cfg_last(1'b0),.cfg_re(18'sd0),.cfg_im(18'sd0),
    .cfg_lambda(34'd0),.cfg_ready(cfg_ready),.configured(configured),
    .s_valid(1'b0),.s_last(1'b0),.s_re(18'sd0),.s_im(18'sd0),.s_ready(s_ready),
    .m_valid(m_valid),.m_last(m_last),.m_re(m_re),.m_im(m_im),.m_ready(1'b0),.error(error));
  `include "mmse3_config_check.svh"
  initial begin
    force dut.entry=entry_code;
    force dut.cstate=dut.C_IDLE;
  end
  // Constant element indices and constant RHS rails avoid simulator force
  // dependencies on task variables. Only source operands are overridden;
  // destination arrays remain exclusively driven by the DUT.
  task set_g(input int slot,input bit real_high,imag_high);
    case(slot)
      0: begin
        if(real_high) force dut.gr[0]=40'sh7fffffffff;
        else force dut.gr[0]=40'sh8000000000;
        if(imag_high) force dut.gi[0]=40'sh7fffffffff;
        else force dut.gi[0]=40'sh8000000000;
      end
      1: begin
        if(real_high) force dut.gr[1]=40'sh7fffffffff;
        else force dut.gr[1]=40'sh8000000000;
        if(imag_high) force dut.gi[1]=40'sh7fffffffff;
        else force dut.gi[1]=40'sh8000000000;
      end
      2: begin
        if(real_high) force dut.gr[2]=40'sh7fffffffff;
        else force dut.gr[2]=40'sh8000000000;
        if(imag_high) force dut.gi[2]=40'sh7fffffffff;
        else force dut.gi[2]=40'sh8000000000;
      end
      3: begin
        if(real_high) force dut.gr[3]=40'sh7fffffffff;
        else force dut.gr[3]=40'sh8000000000;
        if(imag_high) force dut.gi[3]=40'sh7fffffffff;
        else force dut.gi[3]=40'sh8000000000;
      end
      4: begin
        if(real_high) force dut.gr[4]=40'sh7fffffffff;
        else force dut.gr[4]=40'sh8000000000;
        if(imag_high) force dut.gi[4]=40'sh7fffffffff;
        else force dut.gi[4]=40'sh8000000000;
      end
      5: begin
        if(real_high) force dut.gr[5]=40'sh7fffffffff;
        else force dut.gr[5]=40'sh8000000000;
        if(imag_high) force dut.gi[5]=40'sh7fffffffff;
        else force dut.gi[5]=40'sh8000000000;
      end
      6: begin
        if(real_high) force dut.gr[6]=40'sh7fffffffff;
        else force dut.gr[6]=40'sh8000000000;
        if(imag_high) force dut.gi[6]=40'sh7fffffffff;
        else force dut.gi[6]=40'sh8000000000;
      end
      7: begin
        if(real_high) force dut.gr[7]=40'sh7fffffffff;
        else force dut.gr[7]=40'sh8000000000;
        if(imag_high) force dut.gi[7]=40'sh7fffffffff;
        else force dut.gi[7]=40'sh8000000000;
      end
      8: begin
        if(real_high) force dut.gr[8]=40'sh7fffffffff;
        else force dut.gr[8]=40'sh8000000000;
        if(imag_high) force dut.gi[8]=40'sh7fffffffff;
        else force dut.gi[8]=40'sh8000000000;
      end
      default:$fatal(1,"[MMSE3_CONFIG_DIRECTED] invalid G slot");
    endcase
  endtask
  task set_a(input int slot,input bit real_high,imag_high);
    case(slot)
      0: begin
        if(real_high) force dut.ar[0]=84'sh7ffffffffffffffffffff;
        else force dut.ar[0]=84'sh800000000000000000000;
        if(imag_high) force dut.ai[0]=84'sh7ffffffffffffffffffff;
        else force dut.ai[0]=84'sh800000000000000000000;
      end
      1: begin
        if(real_high) force dut.ar[1]=84'sh7ffffffffffffffffffff;
        else force dut.ar[1]=84'sh800000000000000000000;
        if(imag_high) force dut.ai[1]=84'sh7ffffffffffffffffffff;
        else force dut.ai[1]=84'sh800000000000000000000;
      end
      2: begin
        if(real_high) force dut.ar[2]=84'sh7ffffffffffffffffffff;
        else force dut.ar[2]=84'sh800000000000000000000;
        if(imag_high) force dut.ai[2]=84'sh7ffffffffffffffffffff;
        else force dut.ai[2]=84'sh800000000000000000000;
      end
      3: begin
        if(real_high) force dut.ar[3]=84'sh7ffffffffffffffffffff;
        else force dut.ar[3]=84'sh800000000000000000000;
        if(imag_high) force dut.ai[3]=84'sh7ffffffffffffffffffff;
        else force dut.ai[3]=84'sh800000000000000000000;
      end
      4: begin
        if(real_high) force dut.ar[4]=84'sh7ffffffffffffffffffff;
        else force dut.ar[4]=84'sh800000000000000000000;
        if(imag_high) force dut.ai[4]=84'sh7ffffffffffffffffffff;
        else force dut.ai[4]=84'sh800000000000000000000;
      end
      5: begin
        if(real_high) force dut.ar[5]=84'sh7ffffffffffffffffffff;
        else force dut.ar[5]=84'sh800000000000000000000;
        if(imag_high) force dut.ai[5]=84'sh7ffffffffffffffffffff;
        else force dut.ai[5]=84'sh800000000000000000000;
      end
      6: begin
        if(real_high) force dut.ar[6]=84'sh7ffffffffffffffffffff;
        else force dut.ar[6]=84'sh800000000000000000000;
        if(imag_high) force dut.ai[6]=84'sh7ffffffffffffffffffff;
        else force dut.ai[6]=84'sh800000000000000000000;
      end
      7: begin
        if(real_high) force dut.ar[7]=84'sh7ffffffffffffffffffff;
        else force dut.ar[7]=84'sh800000000000000000000;
        if(imag_high) force dut.ai[7]=84'sh7ffffffffffffffffffff;
        else force dut.ai[7]=84'sh800000000000000000000;
      end
      8: begin
        if(real_high) force dut.ar[8]=84'sh7ffffffffffffffffffff;
        else force dut.ar[8]=84'sh800000000000000000000;
        if(imag_high) force dut.ai[8]=84'sh7ffffffffffffffffffff;
        else force dut.ai[8]=84'sh800000000000000000000;
      end
      default:$fatal(1,"[MMSE3_CONFIG_DIRECTED] invalid A slot");
    endcase
  endtask
  task set_h(input int slot,input bit real_high,imag_high);
    case(slot)
      0: begin
        if(real_high) force dut.hr[0]=18'sd131071;
        else force dut.hr[0]=18'sh20000;
        if(imag_high) force dut.hi[0]=18'sd131071;
        else force dut.hi[0]=18'sh20000;
      end
      1: begin
        if(real_high) force dut.hr[1]=18'sd131071;
        else force dut.hr[1]=18'sh20000;
        if(imag_high) force dut.hi[1]=18'sd131071;
        else force dut.hi[1]=18'sh20000;
      end
      2: begin
        if(real_high) force dut.hr[2]=18'sd131071;
        else force dut.hr[2]=18'sh20000;
        if(imag_high) force dut.hi[2]=18'sd131071;
        else force dut.hi[2]=18'sh20000;
      end
      3: begin
        if(real_high) force dut.hr[3]=18'sd131071;
        else force dut.hr[3]=18'sh20000;
        if(imag_high) force dut.hi[3]=18'sd131071;
        else force dut.hi[3]=18'sh20000;
      end
      4: begin
        if(real_high) force dut.hr[4]=18'sd131071;
        else force dut.hr[4]=18'sh20000;
        if(imag_high) force dut.hi[4]=18'sd131071;
        else force dut.hi[4]=18'sh20000;
      end
      5: begin
        if(real_high) force dut.hr[5]=18'sd131071;
        else force dut.hr[5]=18'sh20000;
        if(imag_high) force dut.hi[5]=18'sd131071;
        else force dut.hi[5]=18'sh20000;
      end
      6: begin
        if(real_high) force dut.hr[6]=18'sd131071;
        else force dut.hr[6]=18'sh20000;
        if(imag_high) force dut.hi[6]=18'sd131071;
        else force dut.hi[6]=18'sh20000;
      end
      7: begin
        if(real_high) force dut.hr[7]=18'sd131071;
        else force dut.hr[7]=18'sh20000;
        if(imag_high) force dut.hi[7]=18'sd131071;
        else force dut.hi[7]=18'sh20000;
      end
      8: begin
        if(real_high) force dut.hr[8]=18'sd131071;
        else force dut.hr[8]=18'sh20000;
        if(imag_high) force dut.hi[8]=18'sd131071;
        else force dut.hi[8]=18'sh20000;
      end
      default:$fatal(1,"[MMSE3_CONFIG_DIRECTED] invalid H slot");
    endcase
  endtask
  task automatic pulse;
    #1;clk=1;#1;clk=0;#1;
  endtask
  task automatic verify_stage(input int stage,row,col);
    logic signed [127:0] raw[0:1],actual,narrow;
    int bank;
    for(int c=0;c<2;c++) begin
      case(stage)
        1:begin raw[c]=mm3_cfg_adj(row,col,1'(c));actual=128'(dut.adjugate(row,col,1'(c)));narrow=128'(ADJ_WIDTH'(raw[c]));end
        2:begin raw[c]=mm3_cfg_det(1'(c));actual=128'(dut.determinant(1'(c)));narrow=128'(DET_WIDTH'(raw[c]));end
        3:begin raw[c]=mm3_cfg_m(row,col,1'(c));actual=128'(dut.mentry(row,col,1'(c)));narrow=128'(M_WIDTH'(raw[c]));end
        default:$fatal(1,"[MMSE3_CONFIG_DIRECTED] invalid stage");
      endcase
      if(actual!==raw[c]||narrow!==raw[c])
        $fatal(1,"[MMSE3_CONFIG_DIRECTED] stage=%0d row=%0d col=%0d component=%0d raw=%0d actual=%0d",stage,row,col,c,raw[c],actual);
      bank=2*(stage-1)+c;
      if(checks[bank]==0||raw[c]<extrema_min[bank]) extrema_min[bank]=raw[c];
      if(checks[bank]==0||raw[c]>extrema_max[bank]) extrema_max[bank]=raw[c];
      checks[bank]++;
    end
    pulse;
    for(int c=0;c<2;c++) begin
      case(stage)
        1:actual=c?128'(dut.ai[3*row+col]):128'(dut.ar[3*row+col]);
        2:actual=c?128'(dut.determinant(1)):128'(dut.det);
        3:actual=c?128'(dut.mi[3*row+col]):128'(dut.mr[3*row+col]);
        default:actual=0;
      endcase
      if(actual!==raw[c]) $fatal(1,"[MMSE3_CONFIG_DIRECTED] stored stage=%0d component=%0d",stage,c);
    end
  endtask
  initial begin
    for(int b=0;b<6;b++) begin checks[b]=0;extrema_min[b]=0;extrema_max[b]=0;end
    rst=RESET_ACTIVE;pulse;rst=!RESET_ACTIVE;
    // All 2^8 corner assignments to each cofactor's four independent complex
    // G entries, for every output position (both cofactor sign parities).
    force dut.cstate=dut.C_ADJ;
    for(int row=0;row<3;row++) for(int col=0;col<3;col++) begin
      int ra,rb,ca,cb,indices[0:3];
      ra=col==0?1:0;rb=col==2?1:2;ca=row==0?1:0;cb=row==2?1:2;
      indices[0]=3*ra+ca;indices[1]=3*rb+cb;indices[2]=3*ra+cb;indices[3]=3*rb+ca;
      entry_code=4'(3*row+col);
      for(int mask=0;mask<256;mask++) begin
        for(int k=0;k<4;k++) begin
          set_g(indices[k],1'(mask>>(2*k)),1'(mask>>(2*k+1)));
        end
        verify_stage(1,row,col);
      end
    end
    // Every corner of the twelve independent G40/A84 operands consumed by
    // the first-row / first-column determinant expansion.
    force dut.cstate=dut.C_DET;entry_code=0;
    for(int mask=0;mask<4096;mask++) begin
      for(int k=0;k<3;k++) begin
        set_g(k,1'(mask>>(2*k)),1'(mask>>(2*k+1)));
        set_a(3*k,1'(mask>>(6+2*k)),1'(mask>>(7+2*k)));
      end
      verify_stage(2,0,0);
    end
    // Every corner of twelve independent A84/H18 operands for each of the
    // nine M entries. This exercises row/column mapping and conjugate signs.
    force dut.cstate=dut.C_M;
    for(int row=0;row<3;row++) for(int col=0;col<3;col++) begin
      entry_code=4'(3*row+col);
      for(int mask=0;mask<4096;mask++) begin
        for(int k=0;k<3;k++) begin
          set_a(3*row+k,1'(mask>>(2*k)),1'(mask>>(2*k+1)));
          set_h(3*col+k,1'(mask>>(6+2*k)),1'(mask>>(7+2*k)));
        end
        verify_stage(3,row,col);
      end
    end
    force dut.cstate=dut.C_IDLE;
    // Explicit extrema witnesses. Let Lg=2^39, La=2^83, Lh=2^17.
    // Products range [-La*Lb+min(La,Lb), La*Lb]. Balanced +/-
    // four-term cofactors attain +/- (2^80-2^40), including sign parity.
    for(int c=0;c<2;c++) begin
      if(extrema_min[c]!==-((128'sd1<<<80)-(128'sd1<<<40))||
         extrema_max[c]!== ((128'sd1<<<80)-(128'sd1<<<40)))
        $fatal(1,"[MMSE3_CONFIG_DIRECTED] ADJ extrema component=%0d",c);
    end
    if(extrema_max[3]!==6*(128'sd1<<<122)||extrema_min[3]!==6*(-(128'sd1<<<122)+(128'sd1<<<39)))
      $fatal(1,"[MMSE3_CONFIG_DIRECTED] DET imaginary extrema");
    if(extrema_max[4]!==6*(128'sd1<<<100)||extrema_min[4]!==6*(-(128'sd1<<<100)+(128'sd1<<<17)))
      $fatal(1,"[MMSE3_CONFIG_DIRECTED] M real extrema");
    for(int b=0;b<6;b++)
      $display("MMSE3 CONFIG DIRECTED BANK bank=%0d count=%0d min=%0d max=%0d",b,checks[b],extrema_min[b],extrema_max[b]);
    check_mmse3_config;
    $display("PASS MMSE3 CONFIG DIRECTED ADJ_WIDTH=%0d DET_WIDTH=%0d M_WIDTH=%0d adj=%0d det=%0d m=%0d",
      ADJ_WIDTH,DET_WIDTH,M_WIDTH,checks[0]+checks[1],checks[2]+checks[3],checks[4]+checks[5]);
    $finish;
  end
endmodule
