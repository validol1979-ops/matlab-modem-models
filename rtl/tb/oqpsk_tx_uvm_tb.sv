// OQPSK transmitter: shared UVM with 2-bit labels and 8*N+36 samples.
`define TX_INTERFACE oqpsk_tx_uvm_if
`define TX_PACKAGE oqpsk_tx_pilot_uvm_pkg
`define TX_TOP oqpsk_tx_uvm_top
`define TX_DUT oqpsk_tx
`define TX_LABEL_BITS 2
`define TX_TAIL 36
`define TX_INPUT_FILE "/tx_symbols.txt"
`define TX_OUTPUT_FILE "/tx_out.txt"
`define TX_NAME "OQPSK"
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
