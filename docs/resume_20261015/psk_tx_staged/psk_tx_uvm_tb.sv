// Same production bpsk_tx, with its genuine PSK/QAM mapper parameters.
`define TX_INTERFACE psk_tx_uvm_if
`define TX_PACKAGE psk_tx_pilot_uvm_pkg
`define TX_TOP psk_tx_uvm_top
`define TX_DUT bpsk_tx
`define TX_LABEL_BITS `PSK_LABEL_BITS
`define TX_TAIL 32
`define TX_INPUT_FILE "/tx_symbols.txt"
`define TX_OUTPUT_FILE "/tx_out.txt"
`define TX_NAME "PSK"
`define TX_PSK
`include "modem_tx_uvm.svh"
`undef TX_INTERFACE
`undef TX_PACKAGE
`undef TX_TOP
`undef TX_DUT
`undef TX_LABEL_BITS
`undef TX_TAIL
`undef TX_INPUT_FILE
`undef TX_OUTPUT_FILE
`undef TX_NAME
`undef TX_PSK
