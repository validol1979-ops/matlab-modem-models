// BPSK transmitter: shared UVM with 1-bit labels and 8*N+32 samples.
`define TX_INTERFACE bpsk_tx_uvm_if
`define TX_PACKAGE bpsk_tx_pilot_uvm_pkg
`define TX_TOP bpsk_tx_uvm_top
`define TX_DUT bpsk_tx
`define TX_LABEL_BITS 1
`define TX_TAIL 32
`define TX_INPUT_FILE "/bits.txt"
`define TX_OUTPUT_FILE "/tx.txt"
`define TX_NAME "BPSK"
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
