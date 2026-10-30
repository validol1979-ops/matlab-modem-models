// LDPC decoder, flooding schedule (research_core ldpc; bit-exact reference ldpc_fixed.decode).
// Configuration (between transactions): H (m x n <= 2^LOG2MMAX x 2^LOG2NMAX, at most 2^LOG2EMAX
// ones) row-major, one bit per transfer (cfg_last on the last); m, n, the iteration limit,
// the mode (0 sum-product, 1 min-sum, 2 normalised, 3 offset), ALPHA = round(alpha*256) and
// BETA = round(beta*256) are held during it. The ones become an edge list (column per edge,
// first/last edge per row). A transaction is n Q8 LLRs (s_last on the n-th) and gives n
// outputs (hard bit, posterior; m_last on the n-th).
// Per iteration and check row: pass A reads every edge, v = sat16(P[col] - M[edge]) (M = 0 in
// the first iteration), keeps v and the row statistics (min1, min2, first index of min1, the
// sign product and zero count; mode 0: S = sum of PHI(|v|)); pass B forms each new message:
// the other edges' sign (0 if one of them is zero) times the magnitude - min-sum: min of the
// others (min2 on the min1 edge), times ALPHA (mode 2) or minus BETA (mode 3); mode 0:
// INV[S - PHI(own)] - and adds it to the column sum. Then P = sat16(L + sums) for every column,
// and pass D checks the syndrome; decoding stops at a zero syndrome or the iteration limit.
// The schedule is sequential (3 + 4 clocks per edge per iteration plus 2 per edge for the
// syndrome); P, L and the sums are registers, the messages and v live in edge RAMs.
// error is sticky: a matrix of the wrong size, too many ones, a row with fewer than two ones,
// ALPHA above 256 (alpha > 1), or a transaction of the wrong length.
module ldpc_decoder #(
  parameter int LOG2NMAX = 7,
  parameter int LOG2MMAX = 6,
  parameter int LOG2EMAX = 9,
  parameter bit RESET_ACTIVE = 1,
  parameter PHI_FILE = "rtl/common/mem/ldpc_phi.mem",
  parameter INV_FILE = "rtl/common/mem/ldpc_inv.mem"
)(
  input logic clk, rst,
  input logic cfg_valid, cfg_last, cfg_bit,
  input logic [LOG2MMAX:0] cfg_m,
  input logic [LOG2NMAX:0] cfg_n,
  input logic [7:0] cfg_iterations,
  input logic [1:0] cfg_mode,
  input logic [8:0] cfg_alpha,
  input logic [15:0] cfg_beta,
  output logic cfg_ready, configured,
  input logic s_valid, s_last,
  input logic signed [15:0] s_llr,
  output logic s_ready,
  output logic m_valid, m_last, m_bit,
  output logic signed [15:0] m_posterior,
  input logic m_ready,
  output logic error
);
  localparam int NMAX = 1 << LOG2NMAX;
  localparam int MMAX = 1 << LOG2MMAX;
  localparam int EMAX = 1 << LOG2EMAX;
  localparam int SW = 16 + LOG2MMAX + 1;        // column message sums
  wire reset_now = rst == RESET_ACTIVE;
  function automatic logic signed [15:0] sat16(input logic signed [31:0] v);
    if (v > 32'sd32767) return 16'sd32767;
    if (v < -32'sd32768) return 16'sh8000;
    return v[15:0];
  endfunction

  // Configuration and the edge list.
  logic [LOG2MMAX:0] m, cfg_row;
  logic [LOG2NMAX:0] n, cfg_col;
  logic [7:0] iterations;
  logic [1:0] mode;
  logic [8:0] alpha;
  logic [15:0] beta;
  logic [LOG2EMAX:0] edges, row_weight;
  logic cfg_packet_bad;
  logic [LOG2EMAX-1:0] row_first [0:MMAX-1], row_last [0:MMAX-1];
  // Decoding state.
  typedef enum logic [3:0] {IDLE, LOAD, A0, A1, A2, B0, B1, B2, B3, C, D0, D1, OUT} state_t;
  state_t state;
  logic signed [15:0] llr [0:NMAX-1], post [0:NMAX-1];
  logic signed [SW-1:0] acc [0:NMAX-1];
  logic [LOG2NMAX:0] load_index, out_index;
  logic [LOG2MMAX-1:0] row;
  logic [LOG2EMAX-1:0] e;
  logic [7:0] iteration;
  logic first_iteration, syndrome_bad, parity;
  // Row statistics.
  logic [15:0] min1, min2;
  logic [LOG2EMAX-1:0] min1_edge;
  logic sign_neg;                               // product of the non-zero signs is negative
  logic [LOG2EMAX:0] zeros;
  logic [26:0] phi_sum;
  // Pass B registers.
  logic [LOG2NMAX-1:0] col;
  logic [15:0] mag;
  logic others_zero, others_neg;
  // RAMs: edge column, messages, v.
  wire cfg_take = cfg_valid && cfg_ready;
  wire cfg_packet_start = cfg_row == '0 && cfg_col == '0;
  wire cfg_row_weak = cfg_col == cfg_n - 1'b1 && row_weight + (LOG2EMAX+1)'(cfg_bit) < (LOG2EMAX+1)'(2);
  wire cfg_edge_overflow = cfg_bit && edges >= (LOG2EMAX+1)'(EMAX);
  wire edge_write = cfg_take && cfg_bit && edges < (LOG2EMAX+1)'(EMAX);
  wire [LOG2NMAX-1:0] col_q;
  wire [15:0] msg_q, v_q, phi_q;
  wire [14:0] inv_q;
  wire edge_read = state == A0 || state == B0 || state == D0;
  wire signed [15:0] old_msg = first_iteration ? 16'sd0 : $signed(msg_q);
  wire signed [15:0] v_next = sat16(32'(post[col_q]) - 32'(old_msg));
  wire [15:0] v_abs_next = v_next[15] ? 16'(16'sd0 - v_next) : v_next;
  wire [15:0] v_abs = v_q[15] ? 16'(16'sd0 - $signed(v_q)) : v_q;
  // B3: the new message of edge e.
  wire [15:0] magnitude = mode == 2'd0 ? {1'b0, inv_q} : mag;
  wire signed [15:0] msg_new = others_zero ? 16'sd0 : others_neg ? 16'(16'sd0 - $signed(magnitude)) : $signed(magnitude);
  sync_ram #(.WIDTH(LOG2NMAX),.ADDR_WIDTH(LOG2EMAX)) edge_col(
    .clk(clk),.wr_en(edge_write),.rd_en(edge_read),.wr_addr(LOG2EMAX'(edges)),.rd_addr(e),
    .wr_data(LOG2NMAX'(cfg_col)),.rd_data(col_q));
  sync_ram #(.WIDTH(16),.ADDR_WIDTH(LOG2EMAX)) messages(
    .clk(clk),.wr_en(state == B3),.rd_en(state == A0),.wr_addr(e),.rd_addr(e),.wr_data(msg_new),.rd_data(msg_q));
  sync_ram #(.WIDTH(16),.ADDR_WIDTH(LOG2EMAX)) values(
    .clk(clk),.wr_en(state == A1),.rd_en(state == B0),.wr_addr(e),.rd_addr(e),.wr_data(v_next),.rd_data(v_q));
  // PHI: read in A1 (for S) and in B1 (for the own term); INV: read in B2.
  wire [15:0] phi_arg = state == A1 ? v_abs_next : v_abs;
  wire [12:0] phi_shift = 13'(phi_arg >> 3);
  wire [10:0] phi_index = phi_shift > 13'd2047 ? 11'd2047 : phi_shift[10:0];
  sync_rom #(.WIDTH(16),.ADDR_WIDTH(11),.INIT_FILE(PHI_FILE)) phi(.clk(clk),.rd_en(state == A1 || state == B1),.rd_addr(phi_index),.rd_data(phi_q));
  wire [26:0] t = phi_sum - 27'(phi_q);
  wire [26:0] t_high = (t - 27'd4096) >> 6;
  wire [10:0] inv_index = t < 27'd4096 ? 11'(t >> 2) : 11'd1024 + (t_high > 27'd1023 ? 11'd1023 : 11'(t_high));
  sync_rom #(.WIDTH(15),.ADDR_WIDTH(11),.INIT_FILE(INV_FILE)) inv(.clk(clk),.rd_en(state == B2),.rd_addr(inv_index),.rd_data(inv_q));
  // Min-sum magnitude of the others (min2 on the first min1 edge), then the mode.
  wire [15:0] others_min = e == min1_edge ? min2 : min1;
  // ALPHA <= 256 (alpha <= 1), so the scaled magnitude stays within 16 bits.
  wire [15:0] scaled = 16'((25'(others_min)*25'(alpha) + 25'd128) >> 8);
  wire [15:0] ms_mag = mode == 2'd2 ? scaled : mode == 2'd3 ? (others_min > beta ? others_min - beta : 16'd0) : others_min;
  wire row_end = e == row_last[row];
  wire last_row = 32'(row) == 32'(m) - 1;

  assign cfg_ready = !reset_now && state == IDLE && load_index == '0;
  // Every legal H has at least two entries; its first cfg word starts an atomic
  // matrix load. Keep a concurrent LLR offer pending until that load completes.
  assign s_ready = !reset_now && configured && (state == IDLE || state == LOAD) && !cfg_take;
  wire take = s_valid && s_ready;
  always_ff @(posedge clk) begin
    if (reset_now) begin
      configured <= 0; error <= 0; state <= IDLE; cfg_row <= '0; cfg_col <= '0; edges <= '0; row_weight <= '0;
      cfg_packet_bad <= 0;
      load_index <= '0; m_valid <= 0;
    end else begin
      // Configuration: H row-major into the edge list.
      if (cfg_take) begin
        configured <= 0;
        if (cfg_packet_start) begin
          cfg_packet_bad <= 0;
          m <= cfg_m; n <= cfg_n; iterations <= cfg_iterations; mode <= cfg_mode; alpha <= cfg_alpha; beta <= cfg_beta;
        end
        if (cfg_row_weak || cfg_edge_overflow) cfg_packet_bad <= 1;
        if (cfg_col == '0) row_first[LOG2MMAX'(cfg_row)] <= LOG2EMAX'(edges);
        if (cfg_bit) begin
          if (edges < (LOG2EMAX+1)'(EMAX)) edges <= edges + 1'b1; else error <= 1;
        end
        if (cfg_col == cfg_n - 1'b1) begin
          // Row end: its last edge, and at least two ones.
          row_last[LOG2MMAX'(cfg_row)] <= LOG2EMAX'(edges + (LOG2EMAX+1)'(cfg_bit) - 1'b1);
          if (row_weight + (LOG2EMAX+1)'(cfg_bit) < (LOG2EMAX+1)'(2)) error <= 1;
          row_weight <= '0; cfg_col <= '0; cfg_row <= cfg_row + 1'b1;
        end else begin
          cfg_col <= cfg_col + 1'b1; row_weight <= row_weight + (LOG2EMAX+1)'(cfg_bit);
        end
        if (cfg_last) begin
          cfg_row <= '0; cfg_col <= '0; edges <= '0; row_weight <= '0; cfg_packet_bad <= 0;
          if (cfg_row == cfg_m - 1'b1 && cfg_col == cfg_n - 1'b1 && cfg_m != '0 && cfg_n != '0 &&
              32'(cfg_m) <= MMAX && 32'(cfg_n) <= NMAX && cfg_iterations != '0 && cfg_alpha <= 9'd256 &&
              (!cfg_packet_bad || cfg_packet_start) && !cfg_row_weak && !cfg_edge_overflow) configured <= 1;
          else error <= 1;
        end
      end
      if (m_valid && m_ready) m_valid <= 0;
      case (state)
        IDLE, LOAD: if (take) begin
          llr[LOG2NMAX'(load_index)] <= s_llr; post[LOG2NMAX'(load_index)] <= s_llr; acc[LOG2NMAX'(load_index)] <= '0;
          load_index <= load_index + 1'b1; state <= LOAD;
          if (s_last) begin
            if (load_index != n - 1'b1) error <= 1;
            load_index <= '0; iteration <= 8'd1; first_iteration <= 1; row <= '0; e <= row_first[0];
            min1 <= 16'hffff; min2 <= 16'hffff; sign_neg <= 0; zeros <= '0; phi_sum <= '0; state <= A0;
          end
        end
        // Pass A over the edges of `row`: v, its PHI, the row statistics.
        A0: state <= A1;
        A1: begin
          if (v_next == 16'sd0) zeros <= zeros + 1'b1; else if (v_next < 0) sign_neg <= !sign_neg;
          if (v_abs_next < min1) begin min2 <= min1; min1 <= v_abs_next; min1_edge <= e; end
          else if (v_abs_next < min2) min2 <= v_abs_next;
          state <= A2;
        end
        A2: begin
          phi_sum <= phi_sum + 27'(phi_q);
          if (row_end) begin e <= row_first[row]; state <= B0; end else begin e <= e + 1'b1; state <= A0; end
        end
        // Pass B: the new messages of the same edges.
        B0: state <= B1;
        B1: begin
          col <= col_q;
          // Others: zero if any other v is zero; sign = product of the other non-zero signs.
          others_zero <= zeros - (LOG2EMAX+1)'(v_q == 16'd0) != '0;
          others_neg <= sign_neg ^ v_q[15];
          mag <= ms_mag; state <= B2;
        end
        B2: state <= B3;
        B3: begin
          acc[col] <= acc[col] + SW'(msg_new);
          if (!row_end) begin e <= e + 1'b1; state <= B0; end
          else if (!last_row) begin
            row <= row + 1'b1; e <= row_first[row + 1'b1];
            min1 <= 16'hffff; min2 <= 16'hffff; sign_neg <= 0; zeros <= '0; phi_sum <= '0; state <= A0;
          end else state <= C;
        end
        // Posteriors, then the syndrome over every row.
        C: begin
          for (int c = 0; c < NMAX; c++) begin post[c] <= sat16(32'(llr[c]) + 32'(acc[c])); acc[c] <= '0; end
          row <= '0; e <= row_first[0]; parity <= 0; syndrome_bad <= 0; state <= D0;
        end
        D0: state <= D1;
        D1: begin
          if (row_end) begin
            if (parity ^ post[col_q][15]) syndrome_bad <= 1;
            parity <= 0;
            if (!last_row) begin row <= row + 1'b1; e <= row_first[row + 1'b1]; state <= D0; end
            else if (!(syndrome_bad || parity ^ post[col_q][15]) || iteration == iterations) begin out_index <= '0; state <= OUT; end
            else begin
              iteration <= iteration + 1'b1; first_iteration <= 0; row <= '0; e <= row_first[0];
              min1 <= 16'hffff; min2 <= 16'hffff; sign_neg <= 0; zeros <= '0; phi_sum <= '0; state <= A0;
            end
          end else begin parity <= parity ^ post[col_q][15]; e <= e + 1'b1; state <= D0; end
        end
        OUT: if (!m_valid || m_ready) begin
          m_valid <= 1; m_bit <= post[LOG2NMAX'(out_index)][15]; m_posterior <= post[LOG2NMAX'(out_index)];
          m_last <= out_index == n - 1'b1; out_index <= out_index + 1'b1;
          if (out_index == n - 1'b1) state <= IDLE;
        end
        default: state <= IDLE;
      endcase
    end
  end
endmodule
