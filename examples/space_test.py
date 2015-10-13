import odl
import matplotlib.pyplot as plt

print('\n\n TESTING FOR R^5 \n\n')

spc = odl.Rn(5)

odl.test.SpaceTest(spc).run_tests()

print('\n\n TESTING FOR L2 SPACE \n\n')

spc = odl.L2(odl.Interval(0,1))
disc = odl.l2_uniform_discretization(spc, 100)

odl.test.SpaceTest(disc).run_tests()