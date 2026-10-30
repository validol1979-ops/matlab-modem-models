// Independent issue-time sums from the original input/tap files, not from DUT RAM,
// operands or child nodes. Delay the ideal values to each actual product/tree stage.
localparam int TREE_DEPTH=4+LOG2LANES;
bit [TREE_DEPTH-1:0] tree_reference_valid='0;
longint tree_reference_re[0:LOG2LANES][0:FIR_LANES-1][0:TREE_DEPTH-1];
longint tree_reference_im[0:LOG2LANES][0:FIR_LANES-1][0:TREE_DEPTH-1];
longint product_reference[0:3][0:FIR_LANES-1][0:2];
longint tree_node_checks[0:LOG2LANES];
longint product_word_checks[0:FIR_LANES-1];
int tree_frame_offset=0,tree_frame_length=0;

always @(posedge clk) begin
  if(rst==RESET_ACTIVE) begin
    tree_reference_valid='0;tree_frame_offset=0;tree_frame_length=0;
  end else if($test$plusargs("CHECK_TREE")) begin
    if(scoring&&dut.issue) begin
      if(tree_frame_length==0) begin
        if(tree_frame_offset>=in_total)$fatal(1,"[TREE] extra FIR frame issue");
        for(int q=tree_frame_offset;q<in_total;q++) begin
          tree_frame_length++;
          if(in_last[q])break;
        end
      end
      for(int level=0;level<=LOG2LANES;level++) begin
        for(int node=0;node<(FIR_LANES>>level);node++) begin
          longint re,im;
          re=0;im=0;
          for(int k=0;k<(1<<level);k++) begin
            int tap_index,sample_index;
            longint hr,hi,xr,xi;
            tap_index=int'(dut.step)*FIR_LANES+(node<<level)+k;
            sample_index=int'(dut.n)-tap_index;
            hr=0;hi=0;xr=0;xi=0;
            if(tap_index<tap_total&&sample_index>=0&&sample_index<tree_frame_length) begin
              hr=taps_re[tap_index];hi=taps_im[tap_index];
              xr=in_re[tree_frame_offset+sample_index];xi=in_im[tree_frame_offset+sample_index];
            end
            re+=hr*xr-hi*xi;im+=hr*xi+hi*xr;
            if(level==0) begin
              product_reference[0][node][0]<=hr*xr;product_reference[1][node][0]<=hi*xi;
              product_reference[2][node][0]<=hr*xi;product_reference[3][node][0]<=hi*xr;
            end
          end
          tree_reference_re[level][node][0]<=re;tree_reference_im[level][node][0]<=im;
        end
      end
      if(int'(dut.step)==(tap_total+FIR_LANES-1)/FIR_LANES-1&&int'(dut.n)==tree_frame_length+tap_total-2) begin
        tree_frame_offset+=tree_frame_length;tree_frame_length=0;
      end
    end
    for(int level=0;level<=LOG2LANES;level++)
      for(int node=0;node<(FIR_LANES>>level);node++)
        for(int q=1;q<TREE_DEPTH;q++) begin
          tree_reference_re[level][node][q]<=tree_reference_re[level][node][q-1];
          tree_reference_im[level][node][q]<=tree_reference_im[level][node][q-1];
        end
    for(int axis=0;axis<4;axis++)
      for(int lane=0;lane<FIR_LANES;lane++)
        for(int q=1;q<3;q++)product_reference[axis][lane][q]<=product_reference[axis][lane][q-1];
    tree_reference_valid<={tree_reference_valid[TREE_DEPTH-2:0],scoring&&dut.issue};
  end
end

for(genvar level=0;level<=LOG2LANES;level++) begin:g_check_tree_level
  longint node_checks[0:(FIR_LANES>>level)-1];
  for(genvar node=0;node<(FIR_LANES>>level);node++) begin:g_check_tree_node
    initial begin
      node_checks[node]=0;
      if($bits(dut.g_tree[level].re[node])!=(COMPACT_TREE?36+level:37+LOG2LANES)
         ||$bits(dut.g_tree[level].im[node])!=(COMPACT_TREE?37+level:37+LOG2LANES))
        $fatal(1,"[TREE] unexpected physical node width");
    end
    always @(posedge clk) begin
      if(rst==RESET_ACTIVE)node_checks[node]=0;
      else if(scoring&&$test$plusargs("CHECK_TREE")&&tree_reference_valid[3+level]) begin
        longint observed_re,observed_im;
        observed_re=$signed(dut.g_tree[level].re[node]);observed_im=$signed(dut.g_tree[level].im[node]);
        if($test$plusargs("INJECT_TREE")&&level==LOG2LANES&&node==0)observed_re++;
        if(observed_re!==tree_reference_re[level][node][3+level]
           ||observed_im!==tree_reference_im[level][node][3+level])
          $fatal(1,"[TREE] FIR level %0d node %0d differs before accumulation",level,node);
        node_checks[node]++;
      end
    end
  end
  always_comb begin
    tree_node_checks[level]=0;
    for(int node=0;node<(FIR_LANES>>level);node++)tree_node_checks[level]+=node_checks[node];
  end
end

for(genvar lane=0;lane<FIR_LANES;lane++) begin:g_check_products
  always @(posedge clk) begin
    if(rst==RESET_ACTIVE)product_word_checks[lane]=0;
    else if(scoring&&$test$plusargs("CHECK_TREE")&&tree_reference_valid[2]) begin
      longint observed;
      observed=$signed(dut.p_rr[lane]);
      if($test$plusargs("INJECT_PRODUCT")&&lane==0)observed++;
      if(observed!==product_reference[0][lane][2]
         ||$signed(dut.p_ii[lane])!==product_reference[1][lane][2]
         ||$signed(dut.p_ri[lane])!==product_reference[2][lane][2]
         ||$signed(dut.p_ir[lane])!==product_reference[3][lane][2])
        $fatal(1,"[PRODUCT] FIR exact product differs, lane %0d",lane);
      product_word_checks[lane]+=4;
    end
  end
end

task automatic check_fir_tree();
  longint nodes,products;
  nodes=0;products=0;
  for(int level=0;level<=LOG2LANES;level++) begin
    if(tree_node_checks[level]<1)$fatal(1,"[TREE] unexercised tree level");
    nodes+=tree_node_checks[level];
  end
  for(int lane=0;lane<FIR_LANES;lane++) begin
    if(product_word_checks[lane]<1)$fatal(1,"[PRODUCT] unexercised product lane");
    products+=product_word_checks[lane];
  end
  $display("PASS FIR TREE: %0d %0d %0d",COMPACT_TREE,nodes,products);
endtask
