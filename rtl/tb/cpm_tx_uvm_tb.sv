// MSK/GMSK transmitters: one bit expands to8 samples, plus the GMSK32-sample tail.
`ifndef TX_GMSK
`define TX_GMSK 0
`endif
`define TX_CPM
`define TX_INTERFACE cpm_tx_uvm_if
`define TX_PACKAGE cpm_tx_pilot_uvm_pkg
`define TX_TOP cpm_tx_uvm_top
`define TX_DUT cpm_tx
`define TX_LABEL_BITS 1
`define TX_TAIL (`TX_GMSK?32:0)
`define TX_INPUT_FILE "/tx_symbols.txt"
`define TX_OUTPUT_FILE "/tx_out.txt"
`define TX_NAME (`TX_GMSK?"GMSK":"MSK")
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
`undef TX_CPM
