// Systematic GF(2) encoder (research_core gf2_encode; bit-exact reference ldpc_fixed.encode).
// Configuration (between transactions): the generator A (m x k <= 2^LOG2MMAX x 2^LOG2KMAX)
// row-major, one bit per transfer (cfg_last on the last); cfg_m and cfg_k are held during it.
// A transaction is k message bits (s_last on the k-th) and gives m parity bits (row j:
// XOR of A[j] & message) followed by the k message bits (m_last on the last).
// error is sticky: a matrix of the wrong size or a message of the wrong length.
module gf2_encoder #(
  parameter int LOG2KMAX = 6,
  parameter int LOG2MMAX = 6,
  parameter bit RESET_ACTIVE = 1
)(
  input logic clk, rst,
  input logic cfg_valid, cfg_last, cfg_bit,
  input logic [LOG2MMAX:0] cfg_m,
  input logic [LOG2KMAX:0] cfg_k,
  output logic cfg_ready, configured,
  input logic s_valid, s_last, s_bit,
  output logic s_ready,
  output logic m_valid, m_last, m_bit,
  input logic m_ready,
  output logic error
);
  localparam int KMAX = 1 << LOG2KMAX;
  localparam int MMAX = 1 << LOG2MMAX;
  wire reset_now = rst == RESET_ACTIVE;
  logic [KMAX-1:0] rows [0:MMAX-1];
  logic [LOG2MMAX:0] m, row;
  logic [LOG2KMAX:0] k, col, bit_count;
  logic [KMAX-1:0] message;
  logic emitting;
  logic [LOG2MMAX+LOG2KMAX+1:0] out_index;
  assign cfg_ready = !reset_now && !emitting && bit_count == '0;
  wire cfg_take = cfg_valid && cfg_ready;
  // A complete1x1 matrix may accept its singleton message coherently. Multiword
  // configuration takes priority until it has loaded the entire new matrix.
  wire cfg_single = cfg_last && row == '0 && col == '0 && cfg_m == 1 && cfg_k == 1;
  assign s_ready = !reset_now && configured && !emitting && (!cfg_take || cfg_single);
  wire take = s_valid && s_ready;
  wire total_end = out_index == (LOG2MMAX+LOG2KMAX+2)'(m) + (LOG2MMAX+LOG2KMAX+2)'(k) - 1'b1;
  wire [LOG2MMAX-1:0] parity_row = LOG2MMAX'(out_index);
  wire [LOG2KMAX-1:0] message_bit = LOG2KMAX'(out_index - (LOG2MMAX+LOG2KMAX+2)'(m));
  wire is_parity = out_index < (LOG2MMAX+LOG2KMAX+2)'(m);
  wire parity = ^(rows[parity_row] & message);
  wire next_bit = is_parity ? parity : message[message_bit];
  always_ff @(posedge clk) begin
    if (reset_now) begin
      configured <= 0; error <= 0; row <= '0; col <= '0; bit_count <= '0; emitting <= 0; m_valid <= 0; message <= '0;
    end else begin
      // Configuration: A row-major.
      if (cfg_take) begin
        configured <= 0;
        if (row == '0 && col == '0) begin m <= cfg_m; k <= cfg_k; for (int j = 0; j < MMAX; j++) rows[j] <= '0; end
        if (row < (LOG2MMAX+1)'(MMAX) && col < (LOG2KMAX+1)'(KMAX)) rows[row[LOG2MMAX-1:0]][col[LOG2KMAX-1:0]] <= cfg_bit;
        if (col == cfg_k - 1'b1) begin col <= '0; row <= row + 1'b1; end else col <= col + 1'b1;
        if (cfg_last) begin
          row <= '0; col <= '0;
          if (row == cfg_m - 1'b1 && col == cfg_k - 1'b1 && cfg_m != '0 && cfg_k != '0 &&
              32'(cfg_m) <= MMAX && 32'(cfg_k) <= KMAX) configured <= 1;
          else error <= 1;
        end
      end
      // Message bits, then the output.
      if (take) begin
        message[bit_count[LOG2KMAX-1:0]] <= s_bit;
        if (s_last) begin
          if (bit_count != (cfg_take ? cfg_k : k) - 1'b1) error <= 1;
          bit_count <= '0; emitting <= 1; out_index <= '0;
        end else bit_count <= bit_count + 1'b1;
      end
      if (m_valid && m_ready) m_valid <= 0;
      if (emitting && (!m_valid || m_ready)) begin
        m_valid <= 1; m_bit <= next_bit; m_last <= total_end; out_index <= out_index + 1'b1;
        if (total_end) begin emitting <= 0; message <= '0; end
      end
    end
  end
endmodule
