# Makefile
# See https://docs.cocotb.org/en/stable/quickstart.html for more info

# defaults
SIM ?= icarus
FST ?= -fst # Use more efficient FST format
TOPLEVEL_LANG ?= verilog
SRC_DIR = $(PWD)/../src
PROJECT_SOURCES = project.v spi.v filter_core.v ctl_ff.v

ifneq ($(GATES),yes)

# RTL simulation:
SIM_BUILD				= sim_build/rtl
# spi.v is needed by the unit-test instances in tb.v. It is added here only if
# it is not already listed in PROJECT_SOURCES (defining the modules twice is an error).
# UNIT_SOURCES = $(filter-out $(PROJECT_SOURCES),spi.v)
VERILOG_SOURCES += $(addprefix $(SRC_DIR)/,$(PROJECT_SOURCES)) # $(UNIT_SOURCES))

COMPILE_ARGS    += -DAF_BEHAVIORAL_FF

# top-level tests + per-module SPI unit tests
COCOTB_TEST_MODULES = test,test_spi_unit

else

# Gate level simulation:
SIM_BUILD				= sim_build/gl
COMPILE_ARGS    += -DGL_TEST
COMPILE_ARGS    += -DFUNCTIONAL
COMPILE_ARGS    += -DUSE_POWER_PINS
COMPILE_ARGS    += -DSIM
COMPILE_ARGS    += -DUNIT_DELAY=\#1
VERILOG_SOURCES += $(PDK_ROOT)/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/verilog/primitives.v
VERILOG_SOURCES += $(PDK_ROOT)/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/verilog/gf180mcu_fd_sc_mcu7t5v0.v

# this gets copied in by the GDS action workflow
VERILOG_SOURCES += $(PWD)/gate_level_netlist.v

COCOTB_TEST_MODULES = test

endif

# Allow sharing configuration between design and testbench via `include`:
COMPILE_ARGS 		+= -I$(SRC_DIR)

# Include the testbench sources:
VERILOG_SOURCES += $(PWD)/tb.v
TOPLEVEL = tb

# List test modules to run, separated by commas and without the .py suffix.
# (The RTL branch above also runs test_spi_unit; it is skipped at gate level
# because the netlist does not contain spi_transmit / spi_receive.)
# COCOTB_TEST_MODULES ?= test

# Core unit tests
ifeq ($(SUITE),core)
SIM_BUILD = sim_build/core
COCOTB_RESULTS_FILE       = results_core.xml
VERILOG_SOURCES           = $(SRC_DIR)/filter_core.v $(SRC_DIR)/ctl_ff.v 
COMPILE_ARGS              = -DAF_BEHAVIORAL_FF
COCOTB_HDL_TIMEUNIT       = 1ns
COCOTB_HDL_TIMEPRECISION  = 1ps
TOPLEVEL                  = filter_core
COCOTB_TEST_MODULES       = test_filter_core
endif

ifeq ($(GATES)$(SUITE),)
CUSTOM_SIM_DEPS += core_tests
endif
# include cocotb's make rules to take care of the simulator setup
include $(shell cocotb-config --makefiles)/Makefile.sim

.PHONY: core_tests
core_tests:
	$(MAKE) SUITE=core

# plain `make clean` also cleans the core build (cocotb's clean, SUITE=core settings)
ifeq ($(SUITE),)
clean::
	$(MAKE) SUITE=core clean
endif
