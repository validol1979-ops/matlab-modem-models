#define FFTW_CPP_COMPLEX

#include <vector>
#include <complex>
#include <numeric>
#include <algorithm>
#include <functional>
#include <numeric>
#include <fftw3.h>
#include "mex.h"

// Function prototypes
void phase_correct(std::vector<std::complex<double>>& v, int M, int D);
int get_shift(int M, int D, bool reset = false);
int lcm(int a, int b);
int gcd(int a, int b);

// MEX entry point
void mexFunction(int nlhs, mxArray* plhs[], int nrhs, const mxArray* prhs[]) {
    if (nrhs != 4) {
        mexErrMsgIdAndTxt("MATLAB:wola_chanex:invalidNumInputs",
                          "Usage: Y = wola_chanex(indata, M, D, cofs)");
    }

    // Extract inputs
    double* realData = mxGetPr(prhs[0]);
    double* imagData = mxGetPi(prhs[0]);  // Imaginary part (nullptr if input is real)
    int M = static_cast<int>(mxGetScalar(prhs[1]));
    int D = static_cast<int>(mxGetScalar(prhs[2]));
    double* cofs = mxGetPr(prhs[3]);

    size_t Ndata = mxGetNumberOfElements(prhs[0]);
    size_t Nshift = mxGetNumberOfElements(prhs[3]);
    
    // Initialize complex buffers
    std::vector<std::complex<double>> z(Nshift, {0.0, 0.0});
    size_t Nout = (Ndata - 1) / D;
    std::vector<std::vector<std::complex<double>>> v(Nout, std::vector<std::complex<double>>(M, {0.0, 0.0}));

    // Setup FFTW plan
    fftw_plan p;
    std::vector<std::complex<double>> u(M, {0.0, 0.0});
    std::vector<std::complex<double>> out(M);
    p = fftw_plan_dft_1d(M, (fftw_complex*) &u[0], (fftw_complex*) &out[0], FFTW_FORWARD, FFTW_ESTIMATE);

    size_t rptr = 0;

    // First iteration to preserve phase
    std::complex<double> x(realData[rptr], imagData ? imagData[rptr] : 0.0);
    rptr++;
    
    // Update shift register
    std::rotate(z.begin(), z.begin() + z.size() - 1, z.end());
    z[0] = x;

    // Apply filter weights
    std::vector<std::complex<double>> w(Nshift);
    for (size_t i = 0; i < Nshift; ++i) {
        w[i] = z[i] * cofs[i];
    }

    // Stack and add
    for (size_t i = 0; i < Nshift; i += M) {
        for (size_t j = 0; j < M; ++j) {
            u[j] += w[i + j];
        }
    }
    std::reverse(u.begin() + 1, u.end());

    // Apply phase correction
    phase_correct(u, M, D);

    // FFT
    fftw_execute(p);
    v[0] = out;

    // Iterate for each output sample
    for (size_t kk = 1; kk < Nout; ++kk) {
        std::vector<std::complex<double>> x(D);
        for (size_t i = 0; i < D; ++i) {
            x[i] = std::complex<double>(realData[rptr + i], imagData ? imagData[rptr + i] : 0.0);
        }
        rptr += D;

        // Update shift register
        std::rotate(z.begin(), z.begin() + z.size() - D, z.end());
        std::reverse(x.begin(), x.end());
        std::copy(x.begin(), x.end(), z.begin());

        // Apply filter weights
        for (size_t i = 0; i < Nshift; ++i) {
            w[i] = z[i] * cofs[i];
        }

        // Stack and add
        std::fill(u.begin(), u.end(), std::complex<double>{0.0, 0.0});
        for (size_t i = 0; i < Nshift; i += M) {
            for (size_t j = 0; j < M; ++j) {
                u[j] += w[i + j];
            }
        }
        std::reverse(u.begin() + 1, u.end());

        // Apply phase correction
        phase_correct(u, M, D);

        // FFT
        fftw_execute(p);
        v[kk] = out;
    }

    // Convert result to MATLAB complex output format
    plhs[0] = mxCreateDoubleMatrix((mwSize) Nout, M, mxCOMPLEX);
    double* outReal = mxGetPr(plhs[0]);
    double* outImag = mxGetPi(plhs[0]);

    for (size_t i = 0; i < Nout; ++i) {
        for (size_t j = 0; j < M; ++j) {
            size_t idx = i + j * Nout;
            outReal[idx] = v[i][j].real();
            outImag[idx] = v[i][j].imag();
        }
    }
}

// Helper functions
void phase_correct(std::vector<std::complex<double>>& v, int M, int D) {
    int shift = get_shift(M, D);
    std::rotate(v.begin(), v.begin() + v.size() - shift, v.end());
}

int get_shift(int M, int D, bool reset) {
    static int state = 0;
    static int OL = M - D;
    //static int K = std::lcm(M, D) / D;
    static int K = lcm(M, D) / D;
    

    if (reset) {
        state = 0;
        return 0;
    }

    if (state == 0) state = 1;
    int shift = M - (OL * (state - 1)) % M;
    state = (state + 1) % K;
    if (state == 0) state = K;

    return shift;
}

// Compute GCD using recursion
int gcd(int a, int b) {
    return (b == 0) ? a : gcd(b, a % b);
}

// Compute LCM using GCD
int lcm(int a, int b) {
    return (a / gcd(a, b)) * b;
}
