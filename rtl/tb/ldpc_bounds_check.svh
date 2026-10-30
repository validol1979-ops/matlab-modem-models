// Logical ranges at active LDPC and GF(2) memory accesses. Never inspect idle data.
localparam int LDPC_MMAX=1<<LOG2MMAX;
localparam int LDPC_EMAX=1<<LOG2EMAX;
localparam int GF2_KMAX=1<<LOG2KMAX;
int ldpc_bounds_checks=0,gf2_bounds_checks=0;
bit ldpc_bound_injected=0;
task automatic ldpc_range(input int value,input int low,input int high,input string name);
  if($isunknown(value)||value<low||value>high)
    $fatal(1,"[BOUNDS] LDPC %s: %0d outside [%0d,%0d]",name,value,low,high);
  ldpc_bounds_checks++;
endtask
task automatic gf2_range(input int value,input int low,input int high,input string name);
  if($isunknown(value)||value<low||value>high)
    $fatal(1,"[BOUNDS] GF2 %s: %0d outside [%0d,%0d]",name,value,low,high);
  gf2_bounds_checks++;
endtask
always @(posedge clk) begin
  if(rst==RESET_ACTIVE) begin
    ldpc_bounds_checks=0;gf2_bounds_checks=0;ldpc_bound_injected=0;
  end else if(scoring) begin
    if(dut_ldpc_decoder.cfg_take) begin
      ldpc_range(int'(d_cfg_m),1,LDPC_MMAX,"configured rows");
      ldpc_range(int'(d_cfg_n),1,LDPC_NMAX,"configured columns");
      ldpc_range(int'(dut_ldpc_decoder.cfg_row),0,int'(d_cfg_m)-1,"configuration row");
      ldpc_range(int'(dut_ldpc_decoder.cfg_col),0,int'(d_cfg_n)-1,"configuration column");
      if(d_cfg_bit) ldpc_range(int'(dut_ldpc_decoder.edges),0,LDPC_EMAX-1,"edge write");
    end
    if(dut_ldpc_decoder.take)
      ldpc_range(int'(dut_ldpc_decoder.load_index),0,int'(dut_ldpc_decoder.n)-1,"LLR write");
    if(dut_ldpc_decoder.state inside {dut_ldpc_decoder.A0,dut_ldpc_decoder.A1,dut_ldpc_decoder.A2,
                                        dut_ldpc_decoder.B0,dut_ldpc_decoder.B1,dut_ldpc_decoder.B2,
                                        dut_ldpc_decoder.B3,dut_ldpc_decoder.D0,dut_ldpc_decoder.D1}) begin
      int first_edge,last_edge,edge_value,row_value;
      row_value=int'(dut_ldpc_decoder.row);
      ldpc_range(row_value,0,int'(dut_ldpc_decoder.m)-1,"active row");
      first_edge=int'(dut_ldpc_decoder.row_first[row_value]);
      last_edge=int'(dut_ldpc_decoder.row_last[row_value]);
      ldpc_range(first_edge,0,LDPC_EMAX-1,"row first edge");
      ldpc_range(last_edge,first_edge,LDPC_EMAX-1,"row last edge");
      edge_value=int'(dut_ldpc_decoder.e);
      if(!ldpc_bound_injected&&$test$plusargs("INJECT_BOUND_MISMATCH")) begin
        ldpc_bound_injected=1;
        ldpc_range(LDPC_EMAX,first_edge,last_edge,"injected edge read");
      end
      ldpc_range(edge_value,first_edge,last_edge,"edge read/write");
      if(dut_ldpc_decoder.state inside {dut_ldpc_decoder.A1,dut_ldpc_decoder.B1,dut_ldpc_decoder.D1})
        ldpc_range(int'(dut_ldpc_decoder.col_q),0,int'(dut_ldpc_decoder.n)-1,"edge column read");
      if(dut_ldpc_decoder.state==dut_ldpc_decoder.B3)
        ldpc_range(int'(dut_ldpc_decoder.col),0,int'(dut_ldpc_decoder.n)-1,"message column write");
    end
    if(dut_ldpc_decoder.state==dut_ldpc_decoder.C) begin
      ldpc_range(int'(dut_ldpc_decoder.n),1,LDPC_NMAX,"posterior active columns");
      // The RTL updates all NMAX register slots; only c<n belongs to the logical code.
      for(int column=0;column<int'(dut_ldpc_decoder.n);column++)
        ldpc_range(column,0,int'(dut_ldpc_decoder.n)-1,"posterior read/write");
    end
    if(dut_ldpc_decoder.state==dut_ldpc_decoder.OUT && (!dm_valid||dm_ready))
      ldpc_range(int'(dut_ldpc_decoder.out_index),0,int'(dut_ldpc_decoder.n)-1,"posterior output");

    if(e_cfg_valid&&e_cfg_ready) begin
      gf2_range(int'(e_cfg_m),1,LDPC_MMAX,"configured rows");
      gf2_range(int'(e_cfg_k),1,GF2_KMAX,"configured message bits");
      gf2_range(int'(dut_gf2_encoder.row),0,int'(e_cfg_m)-1,"configuration row");
      gf2_range(int'(dut_gf2_encoder.col),0,int'(e_cfg_k)-1,"configuration column");
    end
    if(dut_gf2_encoder.take)
      gf2_range(int'(dut_gf2_encoder.bit_count),0,int'(dut_gf2_encoder.k)-1,"message write");
    if(dut_gf2_encoder.emitting&&(!em_valid||em_ready)) begin
      gf2_range(int'(dut_gf2_encoder.out_index),0,
                int'(dut_gf2_encoder.m)+int'(dut_gf2_encoder.k)-1,"output read");
      if(dut_gf2_encoder.is_parity)
        gf2_range(int'(dut_gf2_encoder.out_index),0,int'(dut_gf2_encoder.m)-1,"parity row read");
      else
        gf2_range(int'(dut_gf2_encoder.out_index)-int'(dut_gf2_encoder.m),0,
                  int'(dut_gf2_encoder.k)-1,"message bit read");
    end
  end
end
task automatic check_ldpc_bounds();
  if(ldpc_bounds_checks<=0||gf2_bounds_checks<=0)
    $fatal(1,"[BOUNDS] LDPC/GF2 observers did not see active accesses");
  $display("PASS BOUNDS ldpc: %0d checks",ldpc_bounds_checks+gf2_bounds_checks);
endtask
