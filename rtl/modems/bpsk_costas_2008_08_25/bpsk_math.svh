// Signed nearest-even helpers. Datapaths retain their explicit sized registers.
function automatic signed [63:0] b_round(input logic signed [63:0] value,input integer drop);
 logic signed [63:0] quotient;
 logic [63:0] mask,remainder,half;
 begin
  if(drop==0) b_round=value;
  else begin
   quotient=value>>>drop;mask=(64'd1<<drop)-1;remainder=$unsigned(value)&mask;half=64'd1<<(drop-1);
   b_round=quotient+b_s64_t'(remainder>half||(remainder==half&&quotient[0]));
  end
 end
endfunction
function automatic signed [17:0] b_sat(input logic signed [63:0] value);
 if(value>131071) b_sat=18'sd131071;
 else if(value< -131072) b_sat=18'sh20000;
 else b_sat=b_s18_t'(value);
endfunction
function automatic signed [31:0] b_clip(input logic signed [63:0] value,input logic signed [31:0] limit);
 if(value>b_s64_t'(limit)) b_clip=limit;
 else if(value< -(b_s64_t'(limit))) b_clip=-limit;
 else b_clip=b_s32_t'(value);
endfunction
// QAM16 per-axis levels {a,b} (odd, +-1/+-3) of a table index, in config.json order.
function automatic logic [5:0] q16_levels(input logic [3:0] index);
 case(index)
  4'd0:q16_levels={3'sd3,3'sd3};    4'd1:q16_levels={3'sd1,3'sd3};
  4'd2:q16_levels={3'sd3,3'sd1};    4'd3:q16_levels={3'sd1,3'sd1};
  4'd4:q16_levels={-3'sd3,3'sd3};   4'd5:q16_levels={-3'sd3,3'sd1};
  4'd6:q16_levels={-3'sd1,3'sd3};   4'd7:q16_levels={-3'sd1,3'sd1};
  4'd8:q16_levels={-3'sd3,-3'sd3};  4'd9:q16_levels={-3'sd1,-3'sd3};
  4'd10:q16_levels={-3'sd3,-3'sd1}; 4'd11:q16_levels={-3'sd1,-3'sd1};
  4'd12:q16_levels={3'sd3,-3'sd3};  4'd13:q16_levels={3'sd3,-3'sd1};
  4'd14:q16_levels={3'sd1,-3'sd3};  default:q16_levels={3'sd1,-3'sd1};
 endcase
endfunction
// Table index of the per-axis level codes c = (level-1)/2 in -2..1.
function automatic logic [3:0] q16_index(input logic signed [1:0] ca,input logic signed [1:0] cb);
 case({ca,cb})
  4'b0101:q16_index=4'd0;  4'b0001:q16_index=4'd1;  4'b0100:q16_index=4'd2;  4'b0000:q16_index=4'd3;
  4'b1001:q16_index=4'd4;  4'b1000:q16_index=4'd5;  4'b1101:q16_index=4'd6;  4'b1100:q16_index=4'd7;
  4'b1010:q16_index=4'd8;  4'b1110:q16_index=4'd9;  4'b1011:q16_index=4'd10; 4'b1111:q16_index=4'd11;
  4'b0110:q16_index=4'd12; 4'b0111:q16_index=4'd13; 4'b0010:q16_index=4'd14; default:q16_index=4'd15;
 endcase
endfunction
// x times an odd level in -3..3 by shift and add (no multiplier).
function automatic logic signed [20:0] q16_scale(input logic signed [17:0] x,input logic signed [2:0] level);
 logic signed [20:0] magnitude;
 begin
  magnitude=(level==3'sd3||level==-3'sd3)?b_s21_t'(x)+(b_s21_t'(x)<<<1):b_s21_t'(x);
  q16_scale=level<0?-magnitude:magnitude;
 end
endfunction
// Q16 reciprocal round(2^16/n) of the squared level norm n = a^2+b^2 in {2,10,18}.
function automatic logic [15:0] q16_reciprocal(input logic [5:0] levels);
 logic [2:0] ma,mb;
 begin
  ma=levels[5]?-levels[5:3]:levels[5:3];mb=levels[2]?-levels[2:0]:levels[2:0];
  if(ma==3&&mb==3) q16_reciprocal=16'd3641;
  else if(ma==3||mb==3) q16_reciprocal=16'd6554;
  else q16_reciprocal=16'd32768;
 end
endfunction
// QAM64 per-axis levels {a,b} (4-bit signed, odd, +-1..+-7) of a table index, config.json order.
function automatic logic [7:0] q64_levels(input logic [5:0] index);
 case(index)
  6'd0:q64_levels=8'b00010001;
  6'd1:q64_levels=8'b00110001;
  6'd2:q64_levels=8'b00010011;
  6'd3:q64_levels=8'b00110011;
  6'd4:q64_levels=8'b01110001;
  6'd5:q64_levels=8'b01010001;
  6'd6:q64_levels=8'b01110011;
  6'd7:q64_levels=8'b01010011;
  6'd8:q64_levels=8'b00010111;
  6'd9:q64_levels=8'b00110111;
  6'd10:q64_levels=8'b00010101;
  6'd11:q64_levels=8'b00110101;
  6'd12:q64_levels=8'b01110111;
  6'd13:q64_levels=8'b01010111;
  6'd14:q64_levels=8'b01110101;
  6'd15:q64_levels=8'b01010101;
  6'd16:q64_levels=8'b00011111;
  6'd17:q64_levels=8'b00011101;
  6'd18:q64_levels=8'b00111111;
  6'd19:q64_levels=8'b00111101;
  6'd20:q64_levels=8'b00011001;
  6'd21:q64_levels=8'b00011011;
  6'd22:q64_levels=8'b00111001;
  6'd23:q64_levels=8'b00111011;
  6'd24:q64_levels=8'b01111111;
  6'd25:q64_levels=8'b01111101;
  6'd26:q64_levels=8'b01011111;
  6'd27:q64_levels=8'b01011101;
  6'd28:q64_levels=8'b01111001;
  6'd29:q64_levels=8'b01111011;
  6'd30:q64_levels=8'b01011001;
  6'd31:q64_levels=8'b01011011;
  6'd32:q64_levels=8'b11110001;
  6'd33:q64_levels=8'b11110011;
  6'd34:q64_levels=8'b11010001;
  6'd35:q64_levels=8'b11010011;
  6'd36:q64_levels=8'b11110111;
  6'd37:q64_levels=8'b11110101;
  6'd38:q64_levels=8'b11010111;
  6'd39:q64_levels=8'b11010101;
  6'd40:q64_levels=8'b10010001;
  6'd41:q64_levels=8'b10010011;
  6'd42:q64_levels=8'b10110001;
  6'd43:q64_levels=8'b10110011;
  6'd44:q64_levels=8'b10010111;
  6'd45:q64_levels=8'b10010101;
  6'd46:q64_levels=8'b10110111;
  6'd47:q64_levels=8'b10110101;
  6'd48:q64_levels=8'b11111111;
  6'd49:q64_levels=8'b11011111;
  6'd50:q64_levels=8'b11111101;
  6'd51:q64_levels=8'b11011101;
  6'd52:q64_levels=8'b10011111;
  6'd53:q64_levels=8'b10111111;
  6'd54:q64_levels=8'b10011101;
  6'd55:q64_levels=8'b10111101;
  6'd56:q64_levels=8'b11111001;
  6'd57:q64_levels=8'b11011001;
  6'd58:q64_levels=8'b11111011;
  6'd59:q64_levels=8'b11011011;
  6'd60:q64_levels=8'b10011001;
  6'd61:q64_levels=8'b10111001;
  6'd62:q64_levels=8'b10011011;
  default:q64_levels=8'b10111011;
 endcase
endfunction
// Table index of the per-axis level codes c = (level-1)/2 in -4..3.
function automatic logic [5:0] q64_index(input logic signed [2:0] ca,input logic signed [2:0] cb);
 case({ca,cb})
  6'b000000:q64_index=6'd0;
  6'b001000:q64_index=6'd1;
  6'b000001:q64_index=6'd2;
  6'b001001:q64_index=6'd3;
  6'b011000:q64_index=6'd4;
  6'b010000:q64_index=6'd5;
  6'b011001:q64_index=6'd6;
  6'b010001:q64_index=6'd7;
  6'b000011:q64_index=6'd8;
  6'b001011:q64_index=6'd9;
  6'b000010:q64_index=6'd10;
  6'b001010:q64_index=6'd11;
  6'b011011:q64_index=6'd12;
  6'b010011:q64_index=6'd13;
  6'b011010:q64_index=6'd14;
  6'b010010:q64_index=6'd15;
  6'b000111:q64_index=6'd16;
  6'b000110:q64_index=6'd17;
  6'b001111:q64_index=6'd18;
  6'b001110:q64_index=6'd19;
  6'b000100:q64_index=6'd20;
  6'b000101:q64_index=6'd21;
  6'b001100:q64_index=6'd22;
  6'b001101:q64_index=6'd23;
  6'b011111:q64_index=6'd24;
  6'b011110:q64_index=6'd25;
  6'b010111:q64_index=6'd26;
  6'b010110:q64_index=6'd27;
  6'b011100:q64_index=6'd28;
  6'b011101:q64_index=6'd29;
  6'b010100:q64_index=6'd30;
  6'b010101:q64_index=6'd31;
  6'b111000:q64_index=6'd32;
  6'b111001:q64_index=6'd33;
  6'b110000:q64_index=6'd34;
  6'b110001:q64_index=6'd35;
  6'b111011:q64_index=6'd36;
  6'b111010:q64_index=6'd37;
  6'b110011:q64_index=6'd38;
  6'b110010:q64_index=6'd39;
  6'b100000:q64_index=6'd40;
  6'b100001:q64_index=6'd41;
  6'b101000:q64_index=6'd42;
  6'b101001:q64_index=6'd43;
  6'b100011:q64_index=6'd44;
  6'b100010:q64_index=6'd45;
  6'b101011:q64_index=6'd46;
  6'b101010:q64_index=6'd47;
  6'b111111:q64_index=6'd48;
  6'b110111:q64_index=6'd49;
  6'b111110:q64_index=6'd50;
  6'b110110:q64_index=6'd51;
  6'b100111:q64_index=6'd52;
  6'b101111:q64_index=6'd53;
  6'b100110:q64_index=6'd54;
  6'b101110:q64_index=6'd55;
  6'b111100:q64_index=6'd56;
  6'b110100:q64_index=6'd57;
  6'b111101:q64_index=6'd58;
  6'b110101:q64_index=6'd59;
  6'b100100:q64_index=6'd60;
  6'b101100:q64_index=6'd61;
  6'b100101:q64_index=6'd62;
  6'b101101:q64_index=6'd63;
  default:q64_index=6'd0;
 endcase
endfunction
// x times an odd level in -7..7 by shift and add: 3x = 2x+x, 5x = 4x+x, 7x = 8x-x.
function automatic logic signed [21:0] qam_scale(input logic signed [17:0] x,input logic signed [3:0] level);
 logic signed [21:0] w,magnitude;logic [3:0] m;
 begin
  w=b_s22_t'(x);m=level<0?4'(-level):4'(level);
  case(m)
   4'd3:magnitude=w+(w<<<1);
   4'd5:magnitude=w+(w<<<2);
   4'd7:magnitude=(w<<<3)-w;
   default:magnitude=w;
  endcase
  qam_scale=level<0?-magnitude:magnitude;
 end
endfunction
// Q16 reciprocal round(2^16/n), n = a^2+b^2, from the magnitude codes {(|a|-1)/2,(|b|-1)/2}.
function automatic logic [15:0] q64_magnitude_reciprocal(input logic [3:0] codes);
 case(codes)
  4'd0:q64_magnitude_reciprocal=16'd32768;
  4'd1:q64_magnitude_reciprocal=16'd6554;
  4'd2:q64_magnitude_reciprocal=16'd2521;
  4'd3:q64_magnitude_reciprocal=16'd1311;
  4'd4:q64_magnitude_reciprocal=16'd6554;
  4'd5:q64_magnitude_reciprocal=16'd3641;
  4'd6:q64_magnitude_reciprocal=16'd1928;
  4'd7:q64_magnitude_reciprocal=16'd1130;
  4'd8:q64_magnitude_reciprocal=16'd2521;
  4'd9:q64_magnitude_reciprocal=16'd1928;
  4'd10:q64_magnitude_reciprocal=16'd1311;
  4'd11:q64_magnitude_reciprocal=16'd886;
  4'd12:q64_magnitude_reciprocal=16'd1311;
  4'd13:q64_magnitude_reciprocal=16'd1130;
  4'd14:q64_magnitude_reciprocal=16'd886;
  default:q64_magnitude_reciprocal=16'd669;
 endcase
endfunction
