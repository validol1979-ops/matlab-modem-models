// Functional coverage of one output stream for testbenches (not synthesised). data carries FIELDS
// signed numeric fields of FW bits each (field 0 in the low bits); mode is a bench-defined number in
// [0, MODES) for the configuration/mode of the transfer (0 if the bench has one mode).
// The covergroup samples every clock outside reset: transfer/stall/idle, last on a transfer, any field
// at the positive or negative full-scale value (|v| >= 2^(FW-1)-1, both saturation conventions) or
// zero, and the mode. At the end of the simulation one line is printed for tools/coverage_report.py:
// COVER <NAME> group=<%> xfer=<n> stall=<n> last=<n> pos=<n> neg=<n> zero=<n> modes=<m0,m1,...>
module stream_cover #(
  parameter int FIELDS = 2,
  parameter int FW = 18,
  parameter int MODES = 1,
  parameter bit RESET_ACTIVE = 1,
  parameter string NAME = "stream"
)(
  input logic clk, rst,
  input logic valid, ready, last,
  input logic [FIELDS*FW-1:0] data,
  input int mode
);
  localparam longint FULL = (longint'(1) << (FW - 1)) - 1;
  logic pos, neg, zero;
  always_comb begin
    pos = 0; neg = 0; zero = 0;
    for (int f = 0; f < FIELDS; f++) begin
      longint v;
      v = longint'($signed(data[f*FW +: FW]));
      if (v >= FULL) pos = 1;
      if (v <= -FULL) neg = 1;
      if (v == 0) zero = 1;
    end
  end
  wire live = rst != RESET_ACTIVE;
  wire xfer = live && valid && ready;
  covergroup stream_cg @(posedge clk);
    cp_state: coverpoint {valid, ready} iff (live) {bins idle = {2'b00, 2'b01}; bins stall = {2'b10}; bins xfer = {2'b11};}
    cp_last: coverpoint last iff (xfer) {bins inside_frame = {0}; bins end_of_frame = {1};}
    cp_pos: coverpoint pos iff (xfer) {bins full_scale = {1};}
    cp_neg: coverpoint neg iff (xfer) {bins full_scale = {1};}
    cp_zero: coverpoint zero iff (xfer) {bins zero = {1};}
    cp_mode: coverpoint mode iff (xfer) {bins m[] = {[0:MODES-1]};}
    x_stall_last: cross cp_state, cp_last;
  endgroup
  stream_cg cg = new;
  longint n_xfer = 0, n_stall = 0, n_last = 0, n_pos = 0, n_neg = 0, n_zero = 0;
  longint n_mode [0:MODES-1];
  initial for (int m = 0; m < MODES; m++) n_mode[m] = 0;
  always @(posedge clk) if (live) begin
    if (valid && !ready) n_stall++;
    if (xfer) begin
      n_xfer++;
      if (last) n_last++;
      if (pos) n_pos++;
      if (neg) n_neg++;
      if (zero) n_zero++;
      if (mode >= 0 && mode < MODES) n_mode[mode]++;
    end
  end
  final begin
    string modes;
    modes = "";
    for (int m = 0; m < MODES; m++) modes = {modes, (m == 0) ? "" : ",", $sformatf("%0d", n_mode[m])};
    $display("COVER %s group=%0.1f xfer=%0d stall=%0d last=%0d pos=%0d neg=%0d zero=%0d modes=%s",
             NAME, cg.get_inst_coverage(), n_xfer, n_stall, n_last, n_pos, n_neg, n_zero, modes);
  end
endmodule
