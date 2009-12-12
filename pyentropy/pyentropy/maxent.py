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
#    Copyright 2009 Robin Ince

"""
maxent.py -   code for Finite-Alphabet Maximum Entropy solutions using a 
                coordinate transform method

For details of the method see:
    Ince, R. A. A., Petersen, R. S., Swan, D. C., Panzeri, S., 2009
    "Python for Information Theoretic Analysis of Neural Data", 
    Frontiers in Neuroinformatics 3:4 doi:10.3389/neuro.11.004.2009
    http://www.frontiersin.org/neuroinformatics/paper/10.3389/neuro.11/004.2009/
    
If you use this code in a published work, please cite the above paper.

Basic Usage
-----------

# import module
from pyentropy.maxent import AmariSolve

# setup solution for parameters 
# n = number of variables
# m = finite alphabet
a = AmariSolve(n=4,m=5)

# solve maxent preserving marginals of given order
P2 = a.solve(P,k=2)

- P is the probability vector (length m^n -1) of the measured distribution
  whose marginals act as the contraints on the maximum entropy solution.
  P is ordered such that the value of the index is equal to the decimal 
  value of the input state represented, when interpreted as a base m, length n
  word. eg for n=3,m=3:
    P[0] = P(0,0,0)
    P[1] = P(0,0,1)
    P[2] = P(0,0,2)
    P[3] = P(0,1,0)
    P[4] = P(0,1,1) etc.
  This allows efficient vectorised conversion between probability index and 
  response word using base2dec, dec2base. The output is in the same format.

- k is the order of the solution (order of marginals up to which are preserved)

- sometimes to get it to converge it is necessary to play with the initial
  condition for the numerical optimisation using argument eg:
    ic_offset=-0.00001


The code expects a data/ directory where it will store the generated 
transformation matrix for a given parameter set. If it finds one there it will 
load it rather than generating it again, meaning this lengthy step should only 
need to be performed once.

This is a basic version of the code. If you are interested in 
collaborating or would like to check the developments in the most recent lab 
version please contact:
Robin Ince <pyentropy@robince.net>

"""

import time
import os
import sys
import cPickle
import numpy as np
import scipy as sp
import scipy.io as sio
import scipy.sparse as sparse
import scipy.optimize as opt
# umfpack disabled due to bug in scipy
# http://mail.scipy.org/pipermail/scipy-user/2009-December/023625.html
#try:
    #import scikits.umfpack as um
    #HAS_UMFPACK = True
#except:
    #HAS_UMFPACK = False
HAS_UMFPACK = False
from scipy.sparse.linalg import spsolve
from utils import dec2base, base2dec
import ConfigParser

def get_config_file():
    """Get the location and name of the config file for specifying
    the data cache dir. You can call this to find out where to put your
    config.

    """
    if sys.platform.startswith('win'):
        cfname = '~/pyentropy.cfg'
    else:
        cfname = '~/.pyentropy.cfg'
    return os.path.expanduser(cfname)

def get_data_dir():
    """Get the data cache dir to use to load and save precomputed matrices"""
    # default values
    if sys.platform.startswith('win'):
        dirname = '~/_pyentropy'
    else:
        dirname = '~/.pyentropy'
    # try to load user override
    config = ConfigParser.RawConfigParser()
    cf = config.read(get_config_file())
    try:
        data_dir = os.path.expanduser(config.get('maxent','cache_dir'))
    except (ConfigParser.NoSectionError, ConfigParser.NoOptionError):
        data_dir = os.path.expanduser(dirname)

    # check directory exists
    if not os.path.isdir(data_dir):
        try:
            os.mkdir(data_dir)
        except:
            print "ERROR: could not create data dir. Please check your " + \
                  "configuration."
            raise
    return data_dir

#
# AmariSolve class
#
class AmariSolve:
    """A class for computing Amari maximum-entropy solutions.
   
    Methods
    -------
    __init__(n,m) :
        constructor generates/loads transformation matrix
    solve(Pr,k) : 
        maxent solution of a distribution
    theta_from_p(P), eta_from_p(P) :
        Amari coordinate transformations
    si2un(x), un2si(x) : 
        signed integer/unsigned integer conversions

    """

    def __init__(self, n, m, filename='a_', local=False):
        """Setup transformation matrix for given parameter set.

        If existing matrix file is found, load the (sparse) transformation
        matrix A, otherwise generate it.

        Inputs:
        n - number of variables in the system
        m - size of finite alphabet (number of symbols)
        filename='a_' - filename to load/save
                            (designed to be used by derived classes)
                            if None, no file is accessed (force generation)
        local - if True, then store/load arrays from 'data/' directory in 
                current working directory. Otherwise use the package data dir
                (default ~/.pyentropy or ~/_pyentropy (windows))
                Can be overridden through ~/.pyentropy.cfg or ~/pyentropy.cfg 
                (windows)

        """

        #if np.mod(m,2) != 1:
         #   raise ValueError, "m must be odd"

        try: 
            k = self.k
        except AttributeError:
            self.k = n
            
        self.n = n
        self.m = m
        self.l = (m-1)/2
        self.dim = (m**n) - 1

        filename = filename + "n%im%i"%(n,m) 
        if local:
            self.filename = os.path.join(os.getcwd(), 'data', filename)
        else:
            self.filename = os.path.join(get_data_dir(), filename)

        # if file exists load (matrix A)
        # must be running in correct directory
        if filename == None:
            self._generate_matrix()
        elif os.path.exists(self.filename+'.mat'):
            loaddict = sio.loadmat(self.filename+'.mat')
            self.A = loaddict['A'].tocsc()
            self.order_idx = loaddict['order_idx'].squeeze()
        else:
            inkey = raw_input("Existing .mat file not found..." +
                              "Generate matrix? (y/n)")
            if inkey == 'y':
                # else call matrix generation function (and save)
                self._generate_matrix()
            else:
                print "File not found and generation aborted..."
                print "Do not use this class instance."
                return None

        # umfpack factorisation of matrix
        if HAS_UMFPACK:
            self._umfpack()

        return None


    def _umfpack(self):
        self.B = self.A.T
        self.umf = um.UmfpackContext()
        self.umf.numeric(self.B)


    def _calculate_orders(self):
        k = self.k
        n = self.n
        m = self.m
        dim = self.dim
        
        # Calculate the length of each order
        self.order_idx       = np.zeros(n+2, dtype=int) 
        self.order_length    = np.zeros(n+1, dtype=int)
        self.row_counter     = 0

        for ordi in xrange(n+1):    
            self.order_length[ordi] = (sp.comb(n, ordi+1, exact=1) * 
                                        ((m-1)**(ordi+1)))
            self.order_idx[ordi] = self.row_counter
            self.row_counter += self.order_length[ordi]

        self.order_idx[n+1] = dim+1

        # Calculate nnz for A
        # not needed for lil sparse format
        x = (m*np.ones(n))**np.arange(n-1,-1,-1)
        x = x[:k]
        y = self.order_length[:k]
        self.Annz = np.sum(x*y.T)
        

    def _generate_matrix(self):
        """Generate A matrix if required"""
        k = self.k
        n = self.n
        m = self.m
        dim = self.dim

        self._calculate_orders()

        self.A = sparse.dok_matrix((self.order_idx[k],dim))

        self.row_counter = 0
        for ordi in xrange(k):
            self.nterms = m**(n - (ordi+1))
            self.terms = dec2base(np.c_[0:self.nterms,], m, n-(ordi+1))
            self._recloop((ordi+1), 1, [], [], n, m)
            print "Order " + str(ordi+1) + " complete. Time: " + time.ctime()

        # save matrix to file
        self.A = self.A.tocsc()
        savedict = {'A':self.A, 'order_idx':self.order_idx}
        sio.savemat(self.filename, savedict)


    def _recloop(self, order, depth, alpha, pos, n, m, blocksize=None):
        terms = self.terms
        A = self.A
        if not blocksize:
            blocksize = self.nterms

        # starting point for position loop
        if len(pos)==0:
            pos_start = 0
        else:
            pos_start = pos[-1] + 1

        # loop over alphabet
        for ai in xrange(1, m):
            alpha_new = list(alpha)
            alpha_new.append(ai)

            # loop over position
            for pi in xrange(pos_start, (n-(order-depth))):
                pos_new = list(pos)
                pos_new.append(pi)

                # add columns?
                if depth == order:
                    # special case for highest order
                    # (can't insert columns into empty terms array)
                    if order==n:
                        cols = base2dec(np.atleast_2d(alpha_new),m)[0]-1
                        A[self.row_counter, cols] = 1
                    else:    
                        # add columns (insert and add to sparse)
                        ins = np.tile(alpha_new,(blocksize,1))
                        temp = terms
                        for coli in xrange(order):
                            temp = inscol(temp, np.array(ins[:,coli],ndmin=2).T, pos_new[coli])

                        cols = (base2dec(temp,m)-1).tolist()

                        A[self.row_counter, cols] = 1;

                    self.row_counter += 1
                else:
                    self._recloop(order, depth+1, alpha_new, pos_new, n, m, blocksize=blocksize)


    def solve(self,Pr,k,eta_given=False,ic_offset=-0.01, **kwargs):
        """Find Amari maxent distribution for a given order k
        
        Inputs:
        Pr - probability distribution vector
        k - Amari order of interest

        Returns theta vector of Amari solution.

        """
        l       = self.order_idx[k].astype(int)
        theta0  = np.zeros(self.order_idx[-1]-self.order_idx[k]-1)
        x0      = np.zeros(l)+ic_offset 
        sf      = self._solvefunc

        jacobian = kwargs.get('jacobian',True)

        Asmall = self.A[:l,:]
        Bsmall = Asmall.T
        if eta_given:
            eta_sampled = Pr[:l]
        else:
            eta_sampled = Asmall.matvec(Pr)

        if jacobian:
            self.optout = opt.fsolve(sf, x0, (Asmall,Bsmall,eta_sampled, l), 
                fprime=self._jacobian, col_deriv=1, full_output=1)
        else:
            self.optout = opt.fsolve(sf, x0, (Asmall,Bsmall,eta_sampled, l), 
                full_output=1)

        #self.optout = opt.leastsq(sf, x0, (Asmall,Bsmall,eta_sampled), 
                #full_output=1)
        the_k = self.optout[0]

        print "order: " + str(k) + \
                " ierr: " + str(self.optout[2]) + " - " + self.optout[3]
        print "fval: " + str(np.mean(np.abs(self.optout[1]['fvec']))),
        # extra debug info for jacobian 
        print "nfev: %d" % self.optout[1]['nfev'],
        try:
            print "njev: %d" % self.optout[1]['njev']
        except KeyError:
            print ""
        return self._p_from_theta(np.r_[the_k,theta0])


    def _solvefunc(self, theta_un, Asmall, Bsmall, eta_sampled, l):
        b = np.exp(Bsmall.matvec(theta_un))
        y = eta_sampled - ( Asmall.matvec(b) / (b.sum()+1) )
        return y


    def _jacobian(self, theta, Asmall, Bsmall, eta_sampled, l):
        x = np.exp(Bsmall.matvec(theta))
        p = Asmall.matvec(x)
        q = x.sum() + 1

        J = np.outer(p,p)
        xd = sparse.spdiags(x,0,x.size,x.size,format='csc')
        qdp = (Asmall * xd) * Bsmall
        qdp *= q
        J -= qdp
        J /= (q*q)

        return J

    def _p_from_theta(self, theta):
        pnorm = lambda p: ( p / (p.sum()+1) )
        return pnorm(np.exp(self.A.T.matvec(theta)))


    def theta_from_p(self, p):
        b = np.log(p[1:]) - np.log(p[0])
        if HAS_UMFPACK:
            # use prefactored matrix
            theta = self.umf.solve(um.UMFPACK_A, self.B, b, autoTranspose=True)
        else:
            theta = spsolve(self.B, b)
        # add theta(0) or not?
        return theta


    def eta_from_p(self, p):
        return self.A.matvec(p[1:])


    def si2un(self, x):
        """Signed to unsigned integer conversion (in place)"""
        if (x.max() > self.l) or (x.min() < -self.l):
            raise ValueError, "Badly formed input data"
        x[np.where(x<0)] += self.m


    def un2si(self, x):
        "Unsigned to signed integer conversion (in place)"
        if (x.max() > self.m-1) or (x.min() < 0):
            raise ValueError, "Badly formed input data"
        x[np.where(x>self.l)] -= self.m


def inscol(x,h,n):
    xs = x.shape
    hs = h.shape
 
    if hs[0]==1:    # row vector
        h=h.T
        hs=h.shape

    if n==0:
        y = np.hstack((h,x))
    elif n==xs[1]:
        y = np.hstack((x,h))
    else:
        y = np.hstack((x[:,:n],h,x[:,n:]))

    return y


