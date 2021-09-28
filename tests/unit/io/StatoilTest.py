import os
import py
import pytest
import numpy as np
import scipy as sp
import openpnm as op
import networkx as nx
from pathlib import Path


class StatoilTest:

    def setup_class(self):
        ws = op.Workspace()
        ws.settings['local_data'] = True

    def teardown_class(self):
        ws = op.Workspace()
        ws.clear()

    def test_load_F42A(self):
        path = Path(os.path.realpath(__file__),
                    '../../../fixtures/ICL-SandPack(F42A)')
        project = op.io.Statoil.import_data(path=path.resolve(), prefix='F42A')
        assert len(project) == 1
        net = project.network
        assert net.Np == 1246
        assert net.Nt == 2654
        assert np.shape(net['pore.coords']) == (1246, 3)
        assert np.shape(net['throat.conns']) == (2654, 2)
        assert 'pore.radius' in net.keys()

    def test_load_Berea(self):
        path = Path(os.path.realpath(__file__),
                    '../../../fixtures/ICL-Sandstone(Berea)')
        project = op.io.Statoil.import_data(path=path, prefix='Berea')
        assert len(project) == 1
        net = project.network
        assert net.Np == 6298
        assert net.Nt == 12098
        assert np.shape(net['pore.coords']) == (6298, 3)
        assert np.shape(net['throat.conns']) == (12098, 2)
        assert 'pore.radius' in net.keys()
        assert np.all(net.find_neighbor_pores(pores=1000) == [221, 1214])


if __name__ == '__main__':
    # All the tests in this file can be run with 'playing' this file
    t = StatoilTest()
    self = t  # For interacting with the tests at the command line
    t.setup_class()
    for item in t.__dir__():
        if item.startswith('test'):
            print('running test: '+item)
            try:
                t.__getattribute__(item)()
            except TypeError:
                t.__getattribute__(item)(tmpdir=py.path.local())
