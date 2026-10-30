// Simulation-only observer: each enabled lane contributes to field lane % FIELDS.
// Feed the rounded, unclamped value at the actual DUT clamp edge.
module sat_group_check #(
  parameter int VALUES = 2, FIELDS = 2, RAW_WIDTH = 128, OUT_WIDTH = 18,
  parameter bit RESET_ACTIVE = 1,
  parameter logic signed [RAW_WIDTH-1:0] LOW_BOUND = -(RAW_WIDTH'(1) <<< (OUT_WIDTH-1)),
  parameter logic signed [RAW_WIDTH-1:0] HIGH_BOUND = (RAW_WIDTH'(1) <<< (OUT_WIDTH-1)) - 1'b1,
  parameter string NAME = "group", EXPECTED_FILE = "saturation_expected.txt"
)(
  input logic clk, rst, scoring, done,
  input logic valid [0:VALUES-1],
  input logic signed [RAW_WIDTH-1:0] rounded [0:VALUES-1]
);
  localparam logic signed [RAW_WIDTH-1:0] HIGH = HIGH_BOUND;
  localparam logic signed [RAW_WIDTH-1:0] LOW = LOW_BOUND;
  int evaluations [0:FIELDS-1], positive [0:FIELDS-1], negative [0:FIELDS-1];
  int expected_evaluations [0:FIELDS-1], expected_positive [0:FIELDS-1], expected_negative [0:FIELDS-1];
  bit checked = 0;
  string directory;
  int fd, rc, header, extra;
  initial begin
    if (VALUES < FIELDS || VALUES % FIELDS != 0 || OUT_WIDTH >= RAW_WIDTH || OUT_WIDTH < 2 || LOW > HIGH)
      $fatal(1, "[SATURATION] %s: invalid observer parameters", NAME);
    if (!$value$plusargs("VECTORS=%s", directory)) $fatal(1, "[SATURATION] VECTORS missing");
    fd = $fopen({directory,"/",EXPECTED_FILE}, "r");
    if (!fd) $fatal(1, "[SATURATION] %s: missing expected file", NAME);
    rc = $fscanf(fd, "%d", header);
    if (rc != 1 || header != FIELDS) $fatal(1, "[SATURATION] %s: bad header", NAME);
    for (int f=0; f<FIELDS; f++) begin
      rc = $fscanf(fd, "%d %d %d", expected_evaluations[f], expected_positive[f], expected_negative[f]);
      if (rc != 3 || expected_evaluations[f] < 0 || expected_positive[f] < 0 || expected_negative[f] < 0 ||
          expected_positive[f]+expected_negative[f] > expected_evaluations[f])
        $fatal(1, "[SATURATION] %s: bad expected row", NAME);
    end
    if ($fscanf(fd, "%d", extra) == 1) $fatal(1, "[SATURATION] %s: extra rows", NAME);
    $fclose(fd);
    if ($test$plusargs("INJECT_SAT_MISMATCH")) expected_positive[0] += 1;
    if ($test$plusargs("INJECT_SAT_EVAL_MISMATCH")) expected_evaluations[0] += 1;
  end
  always @(posedge clk) begin
    if (rst == RESET_ACTIVE) begin
      checked = 0;
      for (int f=0; f<FIELDS; f++) begin evaluations[f]=0; positive[f]=0; negative[f]=0; end
    end else if (scoring) begin
      for (int i=0; i<VALUES; i++) begin
        if ($isunknown(valid[i])) $fatal(1, "[SATURATION] %s: unknown enable lane %0d", NAME, i);
        if (valid[i]) begin
          if ($isunknown(rounded[i])) $fatal(1, "[SATURATION] %s: unknown lane %0d", NAME, i);
          evaluations[i%FIELDS] += 1;
          if ($signed(rounded[i]) > HIGH) positive[i%FIELDS] += 1;
          if ($signed(rounded[i]) < LOW) negative[i%FIELDS] += 1;
        end
      end
    end
  end
  always @(negedge clk) if (rst != RESET_ACTIVE && scoring && done && !checked) begin
    int total_evaluations, total_events;
    total_evaluations=0; total_events=0;
    for (int f=0; f<FIELDS; f++) begin
      if (evaluations[f] != expected_evaluations[f] || positive[f] != expected_positive[f] || negative[f] != expected_negative[f])
        $fatal(1, "[SATURATION] %s field %0d: eval %0d/%0d pos %0d/%0d neg %0d/%0d", NAME, f,
               evaluations[f], expected_evaluations[f], positive[f], expected_positive[f], negative[f], expected_negative[f]);
      total_evaluations += evaluations[f]; total_events += positive[f]+negative[f];
    end
    $display("PASS SATURATION %s: %0d evaluations, %0d events", NAME, total_evaluations, total_events);
    checked=1;
  end
endmodule
