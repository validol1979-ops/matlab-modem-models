`timescale 1ns/1ps
module bpsk_blocks_tb;
 import uvm_pkg::*;
 `include "uvm_macros.svh"
 parameter bit RESET_ACTIVE=1;
 parameter TABLE_DIR="rtl/modems/bpsk_costas_2008_08_25/tables";
 logic clk=0;always #5 clk=~clk;
 logic rst=RESET_ACTIVE,ce=1,sv=0,sl=0,sfirst=0,sbit=0;
 logic [1:0] frame=0;
 logic signed [17:0] re=0,im=0;
 logic signed [48:0] x=0,y=0;
 logic signed [31:0] phase=0,position=0;
 logic [24:0] gain=0;
 logic [31:0] tag=0;
 logic [14:0] length=0,index=0;
 logic we=0;
 logic signed [63:0] numerator=0;
 logic [31:0] denominator=1;
 wire tv,tl,tr,fv,fl,cv,rv,iv,dv,db;
 wire signed [17:0] tre,tim,fre,fim,rre,rim,ire,iim;
 wire signed [31:0] cp;
 wire [31:0] rt,it;
 wire [15:0] ct;
 wire signed [63:0] dr;
 bpsk_tx #(.RESET_ACTIVE(RESET_ACTIVE)) tx(clk,rst,sv,sbit,sl,tr,ce,tv,tl,tre,tim);
 bpsk_fir #(.RESET_ACTIVE(RESET_ACTIVE)) fir(clk,rst,ce,sv,sl,sfirst,re,im,fv,fl,fre,fim);
 bpsk_cordic #(.RESET_ACTIVE(RESET_ACTIVE)) cordic(clk,rst,ce,sv,x,y,tag[15:0],cv,cp,ct);
 bpsk_rotate #(.RESET_ACTIVE(RESET_ACTIVE),.TABLE_DIR(TABLE_DIR)) rot(clk,rst,ce,sv,re,im,phase[31:20],gain,tag,rv,rre,rim,rt);
 bpsk_samples #(.RESET_ACTIVE(RESET_ACTIVE),.TABLE_DIR(TABLE_DIR)) memory(clk,rst,we,frame,index,re,im,ce,sv,frame,position[31:8],length,tag,iv,ire,iim,it);
 bpsk_divide #(.RESET_ACTIVE(RESET_ACTIVE)) divider(clk,rst,sv,numerator,denominator,db,dv,dr);
 string directory,file;
 integer op=-1,checked=0,expected_count=0,fd,n,rc;
 longint signed expected0[0:19999],expected1[0:19999];
 integer expected_last[0:19999];
 bit running=0,inject=0;
 integer rng_state=1929;
 function automatic bit ready_random();
  rng_state=(rng_state*1664525+1013904223);
  return (rng_state&7)!=0;
 endfunction
 task automatic reset_all;
  @(negedge clk);sv=0;we=0;ce=1;rst=RESET_ACTIVE;
  repeat(4) @(negedge clk);
  rst=!RESET_ACTIVE;repeat(25) @(negedge clk);
 endtask
 task automatic read_expect(input string name,input integer columns);
  fd=$fopen({directory,"/",name,".txt"},"r");if(!fd) $fatal(1,"Missing expected file");
  rc=$fscanf(fd,"%d",expected_count);
  for(integer j=0;j<expected_count;j=j+1) begin
   if(columns==3) rc=$fscanf(fd,"%d %d %d",expected0[j],expected1[j],expected_last[j]);
  end
  $fclose(fd);
 endtask
 task automatic compare(input longint signed a,input longint signed b,input integer last_bit);
  if(checked>=expected_count) `uvm_fatal("NUMERIC","Unexpected output")
  if(a!==(expected0[checked]+longint'(inject&&checked==3))||b!==expected1[checked]||last_bit!=expected_last[checked]) begin
   `uvm_fatal("NUMERIC",$sformatf("op=%0d row=%0d got=(%0d,%0d,%0d) expected=(%0d,%0d,%0d)",op,checked,a,b,last_bit,expected0[checked],expected1[checked],expected_last[checked]))
  end
  checked=checked+1;
 endtask
 always @(posedge clk) if(running&&rst!=RESET_ACTIVE) begin
  case(op)
   0:if(tv&&ce) compare(64'(tre),64'(tim),int'(tl));
   1:if(fv&&ce) compare(64'(fre),64'(fim),int'(fl));
   2:if(cv&&ce) compare(64'(cp),64'(ct),0);
   3:if(rv&&ce) compare(64'(rre),64'(rim),int'(rt));
   4:if(iv&&ce) compare(64'(ire),64'(iim),int'(it));
   5:if(dv) compare(dr,0,0);
  endcase
 end
 property fir_hold;@(posedge clk) disable iff(rst==RESET_ACTIVE) fv&&!ce |=> fv&&$stable({fre,fim,fl});endproperty
 property cordic_hold;@(posedge clk) disable iff(rst==RESET_ACTIVE) cv&&!ce |=> cv&&$stable({cp,ct});endproperty
 property rotate_hold;@(posedge clk) disable iff(rst==RESET_ACTIVE) rv&&!ce |=> rv&&$stable({rre,rim,rt});endproperty
 property interp_hold;@(posedge clk) disable iff(rst==RESET_ACTIVE) iv&&!ce |=> iv&&$stable({ire,iim,it});endproperty
 assert property(fir_hold) else `uvm_fatal("STALL","FIR stalled output changed")
 assert property(cordic_hold) else `uvm_fatal("STALL","CORDIC stalled output changed")
 assert property(rotate_hold) else `uvm_fatal("STALL","Rotation stalled output changed")
 assert property(interp_hold) else `uvm_fatal("STALL","Interpolation stalled output changed")
 initial begin : tests
  longint signed a,b,c,d,e,f;
  if(!$value$plusargs("VECTORS=%s",directory)) $fatal(1,"Missing VECTORS");
  inject=$test$plusargs("INJECT_MISMATCH");
  for(integer mode=0;mode<6;mode=mode+1) begin
   running=0;op=mode;reset_all();checked=0;
   case(mode)
    0:begin read_expect("tx",3);file="bits";end
    1:file="fir";
    2:file="cordic";
    3:file="rotate";
    4:begin
     fd=$fopen({directory,"/memory.txt"},"r");rc=$fscanf(fd,"%d",n);
     for(integer j=0;j<n;j=j+1) begin
      @(negedge clk);rc=$fscanf(fd,"%d %d %d %d",a,b,c,d);
      we=1;frame=2'(a);index=15'(b);re=18'(c);im=18'(d);
     end
     @(negedge clk);we=0;$fclose(fd);file="interp";
    end
    5:file="divide";
   endcase
   fd=$fopen({directory,"/",file,".txt"},"r");rc=$fscanf(fd,"%d",n);
   if(mode!=0) expected_count=n;
   // Load every expected row before any output reaches the scoreboard.
   for(integer j=0;j<n;j=j+1) begin
    case(mode)
     0:begin rc=$fscanf(fd,"%d %d",a,b);expected_last[10000+j]=int'(b);expected0[10000+j]=a;end
     1:begin rc=$fscanf(fd,"%d %d %d %d %d %d",a,b,c,d,e,f);expected0[j]=e;expected1[j]=f;expected_last[j]=int'(d);end
     2:begin rc=$fscanf(fd,"%d %d %d",a,b,c);expected0[j]=c;expected1[j]=j;expected_last[j]=0;end
     3:begin rc=$fscanf(fd,"%d %d %d %d %d %d",a,b,c,d,e,f);expected0[j]=e;expected1[j]=f;expected_last[j]=j;end
     4:begin rc=$fscanf(fd,"%d %d %d %d %d",a,b,c,d,e);expected0[j]=d;expected1[j]=e;expected_last[j]=j;end
     5:begin rc=$fscanf(fd,"%d %d %d",a,b,c);expected0[j]=c;expected1[j]=0;expected_last[j]=0;end
    endcase
   end
   $fclose(fd);fd=$fopen({directory,"/",file,".txt"},"r");rc=$fscanf(fd,"%d",n);running=1;
   for(integer j=0;j<n;j=j+1) begin
    @(negedge clk);ce=ready_random();sv=1;tag=32'(j);
    case(mode)
     0:begin rc=$fscanf(fd,"%d %d",a,b);sbit=1'(a);sl=1'(b);end
     1:begin rc=$fscanf(fd,"%d %d %d %d %d %d",a,b,c,d,e,f);re=18'(a);im=18'(b);sfirst=1'(c);sl=1'(d);end
     2:begin rc=$fscanf(fd,"%d %d %d",a,b,c);x=49'(a);y=49'(b);end
     3:begin rc=$fscanf(fd,"%d %d %d %d %d %d",a,b,c,d,e,f);re=18'(a);im=18'(b);phase=32'(c);gain=25'(d);end
     4:begin rc=$fscanf(fd,"%d %d %d %d %d",a,b,c,d,e);frame=2'(a);position=32'(b);length=15'(c);end
     5:begin rc=$fscanf(fd,"%d %d %d",a,b,c);numerator=a;denominator=32'(b);ce=1;end
    endcase
    // Hold all input data until accepted.
    do begin
     @(posedge clk);
     if(mode==0?tr:(mode==5?!db:ce)) break;
     @(negedge clk);ce=ready_random();
    end while(1);
    if(mode==5) begin @(negedge clk);sv=0;ce=1;wait(dv);@(negedge clk);end
    else if(j%13==4) begin @(negedge clk);sv=0;repeat(2) @(negedge clk);end
   end
   $fclose(fd);@(negedge clk);sv=0;ce=1;
   wait(checked==expected_count);repeat(30) @(negedge clk);running=0;
   $display("PASS BPSK block %0d: %0d exact outputs",mode,checked);
  end
  $display("PASS BPSK blocks");$finish;
 end
 initial begin #10000000;`uvm_fatal("TIMEOUT","BPSK test did not drain") end
endmodule
