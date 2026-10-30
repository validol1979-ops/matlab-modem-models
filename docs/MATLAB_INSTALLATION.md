# MATLAB R2020b

MATLAB is optional. It is used only for the separate runtime/reference checks of historical Simulink models and for the MATLAB variants of the typed suites; the Python, Octave and HDL regressions do not need it. The historical models themselves are not part of the public repository (see [THIRD_PARTY.md](../THIRD_PARTY.md)), so original-model checks run only where those sources are available locally.

The checks were developed with MATLAB R2020b (9.9) under Linux. Use a normally licensed installation obtained from MathWorks.

## Required products

- MATLAB
- Simulink
- Communications Toolbox
- DSP System Toolbox
- Signal Processing Toolbox
- Stateflow
- Fixed-Point Designer

## Launch and validation

From the project root:

```bash
./tools/matlab.sh
./tools/matlab.sh -batch "run('tools/matlab_smoke.m')"
```

The launcher uses `MATLAB_ROOT` if set, otherwise the `matlab` found in `PATH`, otherwise `$HOME/MATLAB/R2020b`. The smoke script checks MATLAB arithmetic, QAM mapping, pulse design, a DSP FIR filter, fixed point arithmetic and a temporary Simulink constant/gain model; the simulation output must equal six at every sample. Stateflow and Signal Processing Toolbox specialized operations are not tested by it.

On newer Linux distributions MATLAB R2020b's bundled FreeType can conflict with the system HarfBuzz (`undefined symbol: FT_Get_Color_Glyph_Layer`). For R2020b the launcher preloads `/usr/lib/x86_64-linux-gnu/libfreetype.so.6`, preserving any existing `LD_PRELOAD` entries. Set `MATLAB_SYSTEM_FREETYPE=0` to disable this adjustment. This process-local workaround follows [MathWorks Support for a similar FreeType conflict](https://www.mathworks.com/matlabcentral/answers/1978579-why-do-some-matlab-features-fail-on-ubuntu-23-04-and-debian-12-with-exit-code-127-in-matlab-r2022b-a).

The installer recommends a supported C compiler for Stateflow, accelerated Simulink simulation, referenced models and MATLAB Function blocks. Compiler compatibility has not been validated.

See [MATLAB modem verification](MATLAB_MODEM_VERIFICATION.md) for numerical reference comparisons and remaining equivalence limits. Noninteractive installation is described in the [MathWorks installation procedure](https://www.mathworks.com/help/install/ug/install-noninteractively-silent-installation.html).
