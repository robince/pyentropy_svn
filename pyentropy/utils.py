#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 2 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
#    Copyright 2008 Robin Ince
""" utils.py

This contains utility functions for working with discrete probability
distributions

"""
from __future__ import division
import numpy as np
from tempfile import NamedTemporaryFile
import os
import subprocess

ent = lambda p: -np.ma.array(p*np.log2(p),copy=False,
            mask=(p<=np.finfo(np.float).eps)).sum(axis=0)


def prob(x, n, method='naive'):
    """Sample probability of integer sequence.

    Parameters
    ----------
    x : int array
        integer input sequence
    n : int
        dimension of input sequence (max(x)<r)
    method: {'naive', 'kt', 'beta:x','shrink'}
        Sampling method to use. 

    Returns
    -------
    Pr : float array
        array representing probability distribution
        Pr[i] = P(x=i)

    """
    if (not np.issubdtype(x.dtype, np.int)): 
        raise ValueError, "Input must be of integer type"

    C = np.bincount(x)
    r = C.size
    if r < n:   # resize if any responses missed
        C.resize((n,))
        C[n:]=0

    return _probcount(C, n, method)


def _probcount(C, N, method='naive'):
    """Estimate probability from a vector of bin counts
    
    Parameters
    ----------
    C : int array
        integer vector of bin counts
    N : int
        number of bins
    method: {'naive', 'kt', 'beta:x','shrink'}
        Sampling method to use. 

    """
    N = float(N)
    if method.lower() == 'naive':
        # normal estimate
        P = C/N
    elif method.lower() == 'kt':
        # KT (constant addition) estimate
        P = (C + 0.5) / (N + (C.size/2.0))
    elif method.lower() == 'shrink':
        # James-Stein shrinkage
        # http://www.strimmerlab.org/software/entropy/index.html
        Pnaive = C/N
        target = 1./C.size
        lam = _get_lambda_shrink(N, Pnaive, target)
        P = (lam * target) + ((1 - lam) * Pnaive)
    elif method.split(':')[0].lower() == 'beta':
        beta = float(method.split(':')[1])
        # general add-constant beta estimate
        P = (C + beta) / (N + (beta*C.size))
    else:
        raise ValueError, 'Unknown sampling method: '+str(est)
    return P


def _get_lambda_shrink(N, u, target):
    """Lambda shrinkage estimator"""
    # *unbiased* estimator of variance of u
    varu = u*(1-u)/(N-1)
    # misspecification
    msp = ((u-target)**2).sum()

    # estimate shrinkage intensity
    if msp == 0:
        lam = 1.
    else:
        lam = (varu/msp).sum()
        
    # truncate
    if lam > 1:
        lam = 1 
    elif lam < 0:
        lam = 0

    return lam


def pt_bayescount(Pr, Nt):
    """Compute the support for analytic bias correction using the 
    Bayesian approach of Panzeri and Treves (1996)
    
    Pr - probability
    Nt - number of trials
    
    """
    
    # dimension of space
    dim = Pr.size

    # non zero probs only
    PrNZ = Pr[Pr>eps]
    Rnaive = PrNZ.size
    
    R = Rnaive
    if Rnaive < dim:
        Rexpected = Rnaive - ((1.0-PrNZ)**Nt).sum()
        deltaR_prev = dim
        deltaR = np.abs(Rnaive - Rexpected)
        xtr = 0.0
        while (deltaR < deltaR_prev) and ((Rnaive+xtr)<dim):
            xtr = xtr+1.0
            Rexpected = 0.0
            # occupied bins
            gamma = xtr*(1.0 - ((Nt/(Nt+Rnaive))**(1.0/Nt)))
            Pbayes = ((1.0-gamma) / (Nt+Rnaive)) * (PrNZ*Nt+1.0)
            Rexpected = (1.0 - (1.0-Pbayes)**Nt).sum()
            # non-occupied bins
            Pbayes = gamma / xtr
            Rexpected = Rexpected + xtr*(1.0 - (1.0 - Pbayes)**Nt)
            deltaR_prev = deltaR
            deltaR = np.abs(Rnaive - Rexpected)
        Rnaive = Rnaive + xtr - 1.0
        if deltaR < deltaR_prev:
            Rnaive += 1.0
    return Rnaive


def nsb_entropy(P, N, dim):
    """Calculate NSB entropy of a probability distribution using
    external nsb-entropy program.

    Inputs:
    P - probability distribution vector
    N - total number of trials
    dim - full dimension of space
    
    """
    
    freqs = np.round(P*N)
    tf = NamedTemporaryFile(mode='w',suffix='.txt')

    # write file header
    tf.file.write("# type: scalar\n")
    tf.file.write(str(dim) + "\n")
    tf.file.write("# rows: 1\n")
    tf.file.write("# columns: " + str(freqs.sum().astype(int)) + "\n")

    # write data
    for i in xrange(freqs.size):
        tf.file.write(freqs[i]*(str(i)+" "))
    tf.file.write("\n")
    tf.file.close()

    # run nsb-entropy application
    subprocess.call(["nsb-entropy","-dpar","-iuni","-cY","-s1","-e1",tf.name[:-4]], 
                    stdout=open(os.devnull),stderr=open(os.devnull))

    # read results
    dir, fname = os.path.split(tf.name)
    out_fname = os.path.splitext(fname)[0]+"_uni_num"+str(dim)+"_mf1f0_1_entr.txt"
    out_fname = os.path.join(dir,out_fname)
    fd = open(out_fname,mode='r')
    results = fd.readlines()
    fd.close()
    os.remove(out_fname)

    H = float(results[15].split(' ')[0])
    dH = float(results[20].split(' ')[0])

    return [H, dH]


def dec2base(x, b, digits):
    """Convert decimal value to a row of values representing it in a 
    given base.
    
    Input x must be a [t,1] column vector (t trials) of integer values

    """
    xs = x.shape
    if xs[1] != 1:
        raise ValueError, "Input x must be a column vector!"

    power = np.ones((xs[0],1)) * (b ** np.c_[digits-1:-0.5:-1,].T)
    x = np.tile(x,(1,digits))
    y = np.floor( np.remainder(x, b*power) / power )
    return y.astype(int)

def base2dec(x, b):
    """Convert a numerical vector to its decimal value in a given base.
    
    Note, this is the same as decimalise except input x is ordered 
    differently (here x[t,n] - ie columns are trials).
    
    """
    xs = x.shape
    z = b**np.arange((xs[1]-1),-0.5,-1)
    y = np.dot(x, z)
    return y.astype(int)


def decimalise(x, n, m):
    """Decimalise discrete response.

    Parameters
    ----------
    x[n,t]: int array
        Vector of samples. Each sample t, is a length-n base-m word.
    n, m : int
        Dimensions of space.

    """
    if x.shape[0] != n or x.max() > m-1:
        raise ValueError, "Input vector x doesnt match parameters"
    powers = m**np.arange(n-1,-0.5,-1,dtype=int)
    d_x = np.dot(x.T,powers).astype(int)

    return d_x


def quantise(input, m, uniform='sampling', minmax=None,
             centers=True):
    """ Quantise 1D input vector into m levels (unsigned)

    uniform : {'sampling','bins'}
        Determine whether quantisation is uniform for sampling (equally 
        occupied bins) or the bins have uniform widths
    minmax : tuple (min,max)
        Specify the range for uniform='bins' quantisation, rather than using
        min/max of input
    centers : bool
        Return vector of bin centers instead of bin bounds

    """
    bin_centers = np.zeros(m)
    if uniform == 'sampling':
        #bin_numel = np.round(input.size/m) - 1
        bin_numel = np.floor(input.size/m)
        stemp = input.copy()
        stemp.sort(axis=0)
        bin_bounds = stemp[bin_numel:-bin_numel+1:bin_numel]
        if centers:
            # calculate center for each bin
            bin_centers[0] =  (bin_bounds[0]+stemp[0]) / 2.0        
            for i in range(1,m-1):
                bin_centers[i] = (bin_bounds[i]+bin_bounds[i-1])/2.0
            bin_centers[m-1] = (stemp[-1]+bin_bounds[-1]) / 2.0
    elif uniform == 'bins':
        if minmax is not None:
            min, max = minmax
        else:
            min, max = input.min(), input.max()
        drange = float(max) - float(min)
        bin_width = drange / float(m)
        bin_bounds = np.arange(1,m,dtype=float)
        bin_bounds *= bin_width
        bin_bounds += min
        if centers:
            bin_centers = r_[bin_bounds - (bin_width/2.0), bin_bounds[-1]+(bin_width/2.0)]
    else:
        raise ValueError, "Unknown value of 'uniform'"

    q_value = np.digitize(input, bin_bounds)

    if centers:
        # bin centers
        return q_value, bin_bounds, bin_centers
    else:
        return q_value, bin_bounds


