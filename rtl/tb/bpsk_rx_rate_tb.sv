// Observer around the existing fixed-model scoreboard, for uninterrupted offers.
// The copied scoreboard has only its historical 32-cycle stall ceiling removed.
`timescale 1ns/1ps
module bpsk_rx_rate_tb;
  parameter bit RESET_ACTIVE = 1;
  parameter integer SYMBOLS = 768;
  parameter integer FRAMES = 4;
  parameter TABLE_DIR = "rtl/modems/bpsk_costas_2008_08_25/tables";
  bpsk_rx_tb #(.RESET_ACTIVE(RESET_ACTIVE), .SYMBOLS(SYMBOLS),
               .TABLE_DIR(TABLE_DIR)) dut_tb();
  integer accepted = 0, offered = 0, blocked = 0, tail_blocked = 0;
  integer other_blocked = 0, frames = 0, cycle = 0, last_cycle = -1;
  integer boundary_gaps = 0, min_gap = 2147483647, max_gap = 0;
  integer tail_due = 0, tail_checks = 0;
  bit awaiting_next = 0, started = 0, held = 0;
  logic [37:0] held_word;
  integer state_wait = 0, state_acquire = 0, state_track = 0, state_retire = 0;
  integer first_block = -1, block_length = 0, block_frame = -1, block_buffer = -1;
  bit in_buffer_block = 0;

  always @(posedge dut_tb.clk) begin
    cycle = cycle + 1;
    if (dut_tb.rst != RESET_ACTIVE) begin
      if (started && frames < FRAMES && dut_tb.sv !== 1'b1)
        $fatal(1, "[RATE] input offer has a gap");
      if (held && {dut_tb.sv,dut_tb.sl,dut_tb.sr,dut_tb.si} !== held_word)
        $fatal(1, "[PROTOCOL] source changed a blocked word");
      held = dut_tb.sv && !dut_tb.rx_ready;
      if (held) held_word = {dut_tb.sv,dut_tb.sl,dut_tb.sr,dut_tb.si};
      if (tail_due > 0) begin
        if (dut_tb.rx_ready !== 1'b0 || dut_tb.g_single.dut.tail == 0)
          $fatal(1, "[RATE] expected 32 cycles of internal FIR flush");
        tail_due = tail_due - 1;
        tail_checks = tail_checks + 1;
      end
      if (dut_tb.g_single.dut.acquisition_done)
        $display("RX EVENT cycle=%0d kind=acquisition_done process_buffer=%0d", cycle, dut_tb.g_single.dut.process_frame);
      if (dut_tb.g_single.dut.tracking_done)
        $display("RX EVENT cycle=%0d kind=tracking_done process_buffer=%0d", cycle, dut_tb.g_single.dut.process_frame);
      if (dut_tb.g_single.dut.state == 3 && dut_tb.g_single.dut.complete[dut_tb.g_single.dut.process_frame])
        $display("RX EVENT cycle=%0d kind=retire process_buffer=%0d", cycle, dut_tb.g_single.dut.process_frame);
      if (dut_tb.sv) begin
        started = 1;
        offered = offered + 1;
        if (!dut_tb.rx_ready) begin
          blocked = blocked + 1;
          if (dut_tb.g_single.dut.tail != 0) tail_blocked = tail_blocked + 1;
          else begin
            other_blocked = other_blocked + 1;
            if (dut_tb.configured !== 1'b1 || dut_tb.error !== 1'b0 ||
                dut_tb.g_single.dut.capture_active !== 1'b0 ||
                dut_tb.g_single.dut.input_count !== 15'd0 ||
                $isunknown(dut_tb.g_single.dut.next_capture) ||
                dut_tb.g_single.dut.occupied[dut_tb.g_single.dut.next_capture] !== 1'b1)
              $fatal(1, "[RATE] non-tail blockage not caused by occupied next buffer");
            case (dut_tb.g_single.dut.state)
              0: state_wait = state_wait + 1;
              1: state_acquire = state_acquire + 1;
              2: state_track = state_track + 1;
              3: state_retire = state_retire + 1;
              default: $fatal(1, "[RATE] unknown receiver state");
            endcase
            if (!in_buffer_block) begin
              in_buffer_block = 1;
              first_block = cycle;
              block_length = 0;
              block_frame = frames;
              block_buffer = dut_tb.g_single.dut.next_capture;
            end
            if (block_frame != frames || block_buffer != dut_tb.g_single.dut.next_capture)
              $fatal(1, "[RATE] blocked buffer/frame changed before acceptance");
            block_length = block_length + 1;
          end
        end else begin
          if (!dut_tb.g_single.dut.capture_active)
            $display("RX RESERVE cycle=%0d frame=%0d buffer=%0d", cycle, frames, dut_tb.g_single.dut.next_capture);
          if (in_buffer_block) begin
            $display("RX BUFFER BLOCK frame=%0d buffer=%0d first=%0d last=%0d cycles=%0d release=%0d",
                     block_frame, block_buffer, first_block, cycle-1, block_length, cycle);
            in_buffer_block = 0;
          end
          accepted = accepted + 1;
          if (awaiting_next) begin
            integer gap;
            gap = cycle - last_cycle - 1;
            boundary_gaps = boundary_gaps + 1;
            if (gap < min_gap) min_gap = gap;
            if (gap > max_gap) max_gap = gap;
            awaiting_next = 0;
          end
          if (dut_tb.sl) begin
            frames = frames + 1;
            last_cycle = cycle;
            tail_due = 32;
            awaiting_next = 1;
          end
        end
      end
    end
  end

  final begin
    $display("RX RATE accepted=%0d offered=%0d blocked=%0d tail_blocked=%0d other_blocked=%0d frames=%0d boundaries=%0d min_gap=%0d max_gap=%0d tail_checks=%0d",
             accepted, offered, blocked, tail_blocked, other_blocked, frames,
             boundary_gaps, min_gap, max_gap, tail_checks);
    $display("RX BLOCK STATES wait=%0d acquire=%0d track=%0d retire=%0d", state_wait, state_acquire, state_track, state_retire);
  end
endmodule
