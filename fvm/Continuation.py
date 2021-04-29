import sys

from math import sqrt

def norm(x):
    return sqrt(x.dot(x))

class Continuation:

    def __init__(self, interface, parameters):
        self.interface = interface
        self.parameters = parameters

        self.newton_iterations = 0
        self.optimal_newton_iterations = self.parameters.get('Optimal Newton Iterations', 3)

        self.min_step_size = self.parameters.get('Minimum Step Size', 10)
        self.max_step_size = self.parameters.get('Maximum Step Size', 2000)

    def newton(self, x0, tol=1.e-7, maxit=1000):
        residual_check = self.parameters.get('Residual Check', 'F')
        verbose = self.parameters.get('Verbose', False)

        x = x0
        for k in range(maxit):
            fval = self.interface.rhs(x)

            if residual_check == 'F' or verbose:
                fnorm = norm(fval)

            if residual_check == 'F' and fnorm < tol:
                print('Newton converged in %d iterations with ||F||=%e' % (k, fnorm))
                sys.stdout.flush()
                break

            jac = self.interface.jacobian(x)
            dx = self.interface.solve(jac, -fval)

            x += dx

            if residual_check != 'F' or verbose:
                dxnorm = norm(dx)

            if residual_check != 'F' and dxnorm < tol:
                print('Newton converged in %d iterations with ||dx||=%e' % (k, dxnorm))
                sys.stdout.flush()
                break

            if verbose:
                print('Newton status at iteration %d: ||F||=%e, ||dx||=%e' % (k, fnorm, dxnorm))
                sys.stdout.flush()

        self.newton_iterations = k

        return x

    def newtoncorrector(self, parameter_name, ds, x, x0, mu, mu0, tol):
        residual_check = self.parameters.get('Residual Check', 'F')
        verbose = self.parameters.get('Verbose', False)

        # Set some parameters
        maxit = self.parameters.get('Maximum Newton Iterations', 10)
        zeta = 1 / len(x)
        delta = 1

        self.newton_iterations = 0

        # Do the main iteration
        for k in range(maxit):

            # Compute F and F_mu (RHS of 2.2.9)
            self.interface.set_parameter(parameter_name, mu + delta)
            dflval = self.interface.rhs(x)
            self.interface.set_parameter(parameter_name, mu)
            fval = self.interface.rhs(x)
            dflval = (dflval - fval) / delta

            if residual_check == 'F' or verbose:
                fnorm = norm(fval)

            if residual_check == 'F' and fnorm < tol:
                print('Newton corrector converged in %d iterations with ||F||=%e' % (k, fnorm))
                sys.stdout.flush()
                break

            # Compute the jacobian at x
            jac = self.interface.jacobian(x)

            # Compute r (2.2.8)
            diff = x - x0
            rnp1 = zeta*diff.dot(diff) + (1 - zeta) * (mu - mu0) ** 2 - ds ** 2

            if self.parameters.get("Bordered Solver", False):
                # Solve the entire bordered system in one go (2.2.9)
                dx, dmu = self.interface.solve(jac, -fval, -rnp1, dflval, 2 * zeta * diff, 2 * (1 - zeta) * (mu - mu0))
            else:
                # Solve twice with F_x (2.2.9)
                z1 = self.interface.solve(jac, -fval)
                z2 = self.interface.solve(jac, dflval)

                # Compute dmu (2.2.13)
                dmu = (-rnp1 - 2 * zeta * diff.dot(z1)) / (2 * (1 - zeta) * (mu - mu0) - 2 * zeta * diff.dot(z2))

                # Compute dx (2.2.12)
                dx = z1 - dmu * z2

            # Compute a new x and mu (2.2.10 - 2.2.11)
            x += dx
            mu += dmu

            self.newton_iterations += 1

            if residual_check != 'F' or verbose:
                dxnorm = norm(dx)

            if residual_check != 'F' and dxnorm < tol:
                print('Newton corrector converged in %d iterations with ||dx||=%e' % (k, dxnorm))
                sys.stdout.flush()
                break

            if verbose:
                print('Newton corrector status at iteration %d: ||F||=%e, ||dx||=%e' % (k, fnorm, dxnorm))
                sys.stdout.flush()

        if self.newton_iterations == maxit:
            print('Newton did not converge. Adjusting step size and trying again')
            return x0, mu0

        return x, mu

    def adjust_step_size(self, ds):
        ''' Step size control, see [Seydel p 188.] '''

        factor = self.optimal_newton_iterations / max(self.newton_iterations, 1)
        factor = min(max(factor, 0.5), 2.0)

        ds *= factor

        return min(max(ds, self.min_step_size), self.max_step_size)

    def continuation(self, x0, parameter_name, target, ds, maxit, verbose=False):
        x = x0

        # Get the initial tangent (2.2.5 - 2.2.7).
        delta = 1
        mu = self.interface.get_parameter(parameter_name)
        fval = self.interface.rhs(x)
        self.interface.set_parameter(parameter_name, mu + delta)
        dmu = (self.interface.rhs(x) - fval) / delta
        self.interface.set_parameter(parameter_name, mu)

        # Compute the jacobian at x and solve with it (2.2.5)
        jac = self.interface.jacobian(x)
        dx = -self.interface.solve(jac, dmu)

        # Scaling of the initial tangent (2.2.7)
        dmu = 1
        zeta = 1 / len(x)
        nrm = sqrt(zeta * dx.dot(dx) + dmu ** 2)
        dmu /= nrm
        dx /= nrm

        # Perform the continuation
        for j in range(maxit):
            mu0 = mu
            x0 = x

            # Predictor (2.2.3)
            mu = mu0 + ds * dmu
            x = x0 + ds * dx

            # Corrector (2.2.9 and onward)
            x, mu = self.newtoncorrector(parameter_name, ds, x, x0, mu, mu0, 1e-4)

            if mu == mu0:
                # No convergence was achieved, adjusting the step size
                prev_ds = ds
                ds = self.adjust_step_size(ds)
                if prev_ds == ds:
                    raise Exception('Newton cannot achieve convergence')

                continue

            print("%s: %f" % (parameter_name, mu))
            sys.stdout.flush()

            if (mu >= target and mu0 < target) or (mu <= target and mu0 > target):
                # Converge onto the end point (we usually go past it, so we
                # use Newton to converge)
                mu = target
                self.interface.set_parameter(parameter_name, mu)
                x = self.newton(x, 1e-8)

                print("%s: %f" % (parameter_name, mu))
                sys.stdout.flush()

                return x

            # Set the new values computed by the corrector
            dmu = mu - mu0
            dx = x - x0

            if abs(dmu) < 1e-10:
                return

            # Compute the tangent (2.2.4)
            dx /= ds
            dmu /= ds

            ds = self.adjust_step_size(ds)

        return x
