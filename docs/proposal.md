# Proposal

## Motivation

The purpose of this project is to design and implement a digital adaptive finite impulse response (FIR) filter with a sign-sign least-mean-squares (LMS) coefficient update engine, providing a general-purpose adaptive filtering architecture with applications in interference cancellation, including maternal heartbeat suppression in fetal electrocardiography as demonstrated by Widrow et al., in *Adaptive Noise Cancelling: Principles and Applications* (Figs. 14–15).

## System Diagram


## Proposed Specifications

| Design Specification | Value |
|---|---:|
| Number of taps (FIR) | 8 |
| Bits per tap | 8 |
| Output precision | 19 |
| Bits per weight | 8 |
| Input frequency | 1 MHz |
| Clock rate | 4 MHz |

## I/O Pin Assignments

| Name | Direction | Assignment |
|---|---|---|
| `clk` | Input | Clock input |
| `rst_n` | Input | Active low reset |
| `ui_in[7:0]` | Input | Time multiplexed input and error |
| `uo_out[7:0]` | Output | Corrected signal or debug outputs |
| `uio[7:0]` | Bidirectional | Set phase of input and output signals, send debug commands. |

## Timeline and Assignments

The timeline is sourced from the course schedule, and consists of the following project stages:

1. Signal simulation
2. Repo setup
3. Design RTL
4. Test with Cocotb
5. Implementation + timing verification
6. DRC evaluation, synthesis, parasitic extraction
7. GitHub Actions

### Maria Tasks

**Create Repo**
- Add information

**Implementation**
- FIR block
- Documentation

**Testing**
- Timing
- Block-level verification
- Synthesis, parasitic extraction

### Aaron Tasks

**Implementation**
- LMS engine
- Documentation

**Testing**
- Block-level verification
- Synthesis, parasitic extraction
- MATLAB coefficient simulation

### Common Tasks

**Simulation**
- MATLAB module simulation

**Implementation**
- Top level module instantiation
- Tiny Tapeout pin connections
- Control FSM

**Testing**
- Timing
- Output verification
- Synthesis, parasitic extraction

## References

B. Widrow et al., "Adaptive noise cancelling: Principles and applications," in *Proceedings of the IEEE*, vol. 63, no. 12, pp. 1692–1716, Dec. 1975, doi: 10.1109/PROC.1975.10036.
