import numpy as np
import scipy.sparse as sprs
from scipy.spatial import cKDTree
from scipy.spatial import ConvexHull
from scipy.spatial import Delaunay
from scipy.sparse import csgraph
from openpnm._skgraph.tools import generate_points_on_sphere
from openpnm._skgraph.tools import generate_points_on_circle
from openpnm._skgraph.tools import cart2sph, sph2cart, cart2cyl, cyl2cart
# from openpnm._skgraph.tools import get_node_prefix, get_edge_prefix


# Once a function has been stripped of all its OpenPNM dependent code it
# can be added to this list of functions to import
__all__ = [
    'get_edge_prefix',
    'get_node_prefix',
    'change_prefix',
    'isoutside',
    'dimensionality',
    'find_surface_nodes',
    'find_surface_nodes_cubic',
    'internode_distance',
    'hull_centroid',
    'tri_to_am',
    'vor_to_am',
    'conns_to_am',
    'am_to_im',
    'im_to_am',
    'dict_to_am',
    'dict_to_im',
    'istriu',
    'istril',
    'istriangular',
    'issymmetric',
]


# This list contains functions that are in the file below but not yet ready
__notyet__ = [
    'is_fully_connected',
    'get_domain_length',
    'get_domain_area',
    'get_shape',
    'get_spacing',
]


def get_edge_prefix(g):
    r"""
    Determines the prefix used for edge arrays from ``<edge_prefix>.conns``

    Parameters
    ----------
    g : dict
        The graph dictionary

    Returns
    -------
    edge_prefix : str
        The value of ``<edge_prefix>`` used in ``g``.  This is found by
        scanning ``g.keys()`` until an array ending in ``'.conns'`` is found,
        then returning the prefix.

    Notes
    -----
    This process is surprizingly fast, on the order of a few doze nano seconds,
    so this overhead is worth it for the flexibility it provides in array
    naming. Since all ``dict`` are now sorted in Python, it may be helpful to
    ensure the ``'conns'`` array is near the beginning of the list.
    """
    for item in g.keys():
        if item.endswith('.conns'):
            return item.split('.')[0]


def get_node_prefix(g):
    r"""
    Determines the prefix used for node arrays from ``<edge_prefix>.coords``

    Parameters
    ----------
    g : dict
        The graph dictionary

    Returns
    -------
    node_prefix : str
        The value of ``<node_prefix>`` used in ``g``.  This is found by
        scanning ``g.keys()`` until an array ending in ``'.coords'`` is found,
        then returning the prefix.

    Notes
    -----
    This process is surprizingly fast, on the order of a few doze nano seconds,
    so this overhead is worth it for the flexibility it provides in array
    naming. Since all ``dict`` are now sorted in Python, it may be helpful to
    ensure the ``'coords'`` array is near the beginning of the list.
    """
    for item in g.keys():
        if item.endswith('.coords'):
            return item.split('.')[0]


def change_prefix(g, old_prefix, new_prefix):
    for item in g.keys():
        if item.startswith(old_prefix):
            key = item.split('.')[1:]
            g[new_prefix + '.' + key] = g.pop(item)
    return g


def isoutside(coords, shape, tolerance=0.0):
    r"""
    Identifies sites that lie outside the specified shape

    Parameters
    ----------
    coords : array_like
        The coordinates which are to be checked
    shape : array_like
        The shape of the domain beyond which points are considered "outside".
        The argument is treated as follows:

        ========== ============================================================
        shape      Interpretation
        ========== ============================================================
        [x, y, z]  A 3D cubic domain of dimension x, y and z with the origin at
                   [0, 0, 0].
        [x, y, 0]  A 2D square domain of size x by y with the origin at
                   [0, 0]
        [r, z]     A 3D cylindrical domain of radius r and height z whose
                   central axis starts at [0, 0, 0]
        [r, 0]     A 2D circular domain of radius r centered on [0, 0] and
                   extending upwards
        [r]        A 3D spherical domain of radius r centered on [0, 0, 0]
        ========== ============================================================

    tolerance : scalar or array_like, optional
        Controls how far a node must be from the domain boundary to be
        considered outside. It is applied as a fraction of the domain size as
        ``x[i] > (shape[0] + shape[0]*threshold)`` or
        ``y[i] < (0 - shape[1]*threshold)``.  Discrete threshold values
        can be given for each axis by supplying a list the same size as
        ``shape``.

    Returns
    -------
    mask : boolean ndarray
        A boolean array with ``True`` values indicating nodes that lie outside
        the domain.

    Notes
    -----
    If the domain is 2D, either a circle or a square, then the z-dimension
    of ``shape`` should be set to 0.

    """
    shape = np.array(shape, dtype=float)
    if np.isscalar(tolerance):
        tolerance = np.array([tolerance]*len(shape))
    else:
        tolerance = np.array(tolerance)
    # Label external pores for trimming below
    if len(shape) == 1:  # Spherical
        # Find external points
        R, Q, P = cart2sph(*coords.T)
        thresh = tolerance[0]*shape[0]
        Ps = R > (shape[0] + thresh)
    elif len(shape) == 2:  # Cylindrical
        # Find external pores outside radius
        R, Q, Z = cart2cyl(*coords.T)
        thresh = tolerance[0]*shape[0]
        Ps = R > shape[0]*(1 + thresh)
        # Find external pores above and below cylinder
        if shape[1] > 0:
            thresh = tolerance[1]*shape[1]
            Ps = Ps + (coords[:, 2] > (shape[1] + thresh))
            Ps = Ps + (coords[:, 2] < (0 - thresh))
        else:
            pass
    elif len(shape) == 3:  # Rectilinear
        thresh = tolerance*shape
        Ps1 = np.any(coords > (shape + thresh), axis=1)
        Ps2 = np.any(coords < (0 - thresh), axis=1)
        Ps = Ps1 + Ps2
    return Ps


def dimensionality(coords):
    r"""
    Checks the dimensionality of the network

    Parameters
    ----------
    coords : ndarray
        The coordinates of the sites

    Returns
    -------
    dims : list
        A  3-by-1 array containing ``True`` for each axis that contains
        multiple values, indicating that the pores are spatially distributed
        in that dimension.

    """
    eps = np.finfo(float).resolution
    dims_unique = [not np.allclose(xk, xk.mean(), atol=0, rtol=eps) for xk in coords.T]
    return np.array(dims_unique)


def find_surface_nodes_cubic(coords):
    r"""
    Identifies nodes on the outer surface of the domain assuming a cubic domain
    to save time

    Parameters
    ----------
    coords : ndarray
        The coordinates of nodes in the network

    Returns
    -------
    mask : ndarray
        A boolean array of ``True`` values indicating which nodes were found
        on the surfaces.
    """
    hits = np.zeros(coords.shape[0], dtype=bool)
    dims = dimensionality(coords)
    for d in range(3):
        if dims[d]:
            hi = np.where(coords[:, d] == coords[:, d].max())[0]
            lo = np.where(coords[:, d] == coords[:, d].min())[0]
            hits[hi] = True
            hits[lo] = True
    return hits


def find_surface_nodes(coords):
    r"""
    Identifies nodes on the outer surface of the domain using a Delaunay
    tessellation

    Parameters
    ----------
    coords : ndarray
        The coordinates of nodes in the network

    Returns
    -------
    mask : ndarray
        A boolean array of ``True`` values indicating which nodes were found
        on the surfaces.

    Notes
    -----
    This function generates points around the domain the performs a Delaunay
    tesselation between these points and the network nodes.  Any network
    nodes which are connected to a generated points is considered a surface
    node.
    """
    coords = np.copy(coords)
    shift = np.mean(coords, axis=0)
    coords = coords - shift
    tmp = cart2sph(*coords.T)
    hits = np.zeros(coords.shape[0], dtype=bool)
    r = 2*tmp[0].max()
    dims = dimensionality(coords)
    if sum(dims) == 1:
        hi = np.where(coords[:, dims] == coords[:, dims].max())[0]
        lo = np.where(coords[:, dims] == coords[:, dims].min())[0]
        hits[hi] = True
        hits[lo] = True
        return hits
    if sum(dims) == 2:
        markers = generate_points_on_circle(n=max(10, int(coords.shape[0]/10)), r=r)
        pts = np.vstack((coords[:, dims], markers))
    else:
        markers = generate_points_on_sphere(n=max(10, int(coords.shape[0]/10)), r=r)
        pts = np.vstack((coords, markers))
    tri = Delaunay(pts, incremental=False)
    (indices, indptr) = tri.vertex_neighbor_vertices
    for k in range(coords.shape[0], tri.npoints):
        neighbors = indptr[indices[k]:indices[k+1]]
        inds = np.where(neighbors < coords.shape[0])
        hits[neighbors[inds]] = True
    return hits


def internode_distance(coords, nodes1=None, nodes2=None):
    r"""
    Find the distance between all nodes on set 1 to each node in set 2

    Parameters
    ----------
    coords : ndarray
        The coordinate of the network nodes
    nodes1 : array_like
        A list containing the indices of the first set of nodes
    nodes2 : array_Like
        A list containing the indices of the first set of nodes.  It's OK if
        these indices are partially or completely duplicating ``nodes1``.

    Returns
    -------
    dist : array_like
        A distance matrix with ``len(site1)`` rows and ``len(sites2)`` columns.
        The distance between site *i* in ``site1`` and *j* in ``sites2`` is
        located at *(i, j)* and *(j, i)* in the distance matrix.

    Notes
    -----
    This function computes and returns a distance matrix, so can get large.
    For distances between larger sets a KD-tree approach would be better,
    which is available in ``scipy.spatial``.

    """
    from scipy.spatial.distance import cdist
    p1 = np.array(nodes1, ndmin=1)
    p2 = np.array(nodes2, ndmin=1)
    return cdist(coords[p1], coords[p2])


def hull_centroid(coords):
    r"""
    Computes centroid of the convex hull enclosing the given coordinates.

    Parameters
    ----------
    coords : Np by 3 ndarray
        Coordinates (xyz)

    Returns
    -------
    centroid : array
        A 3 by 1 Numpy array containing coordinates of the centroid.

    """
    dim = [np.unique(coords[:, i]).size != 1 for i in range(3)]
    hull = ConvexHull(coords[:, dim])
    centroid = coords.mean(axis=0)
    centroid[dim] = hull.points[hull.vertices].mean(axis=0)
    return centroid


def iscoplanar(coords):
    r"""
    Determines if given pores are coplanar with each other

    Parameters
    ----------
    coords : array_like
        List of pore coords to check for coplanarity.  At least 3 pores are
        required.

    Returns
    -------
    results : bool
        A boolean value of whether given points are coplanar (``True``) or
        not (``False``)

    """
    coords = np.array(coords, ndmin=1)
    if np.shape(coords)[0] < 3:
        raise Exception('At least 3 input pores are required')

    Px = coords[:, 0]
    Py = coords[:, 1]
    Pz = coords[:, 2]

    # Do easy check first, for common coordinate
    if np.shape(np.unique(Px))[0] == 1:
        return True
    if np.shape(np.unique(Py))[0] == 1:
        return True
    if np.shape(np.unique(Pz))[0] == 1:
        return True

    # Perform rigorous check using vector algebra
    # Grab first basis vector from list of coords
    n1 = np.array((Px[1] - Px[0], Py[1] - Py[0], Pz[1] - Pz[0])).T
    n = np.array([0.0, 0.0, 0.0])
    i = 1
    while n.sum() == 0:
        if i >= (np.size(Px) - 1):
            return False
        # Chose a secon basis vector
        n2 = np.array((Px[i+1] - Px[i], Py[i+1] - Py[i], Pz[i+1] - Pz[i])).T
        # Find their cross product
        n = np.cross(n1, n2)
        i += 1
    # Create vectors between all other pairs of points
    r = np.array((Px[1:-1] - Px[0], Py[1:-1] - Py[0], Pz[1:-1] - Pz[0]))
    # Ensure they all lie on the same plane
    n_dot = np.dot(n, r)

    return bool(np.sum(np.absolute(n_dot)) == 0)


def is_fully_connected(conns, pores_BC=None):
    r"""
    Checks whether network is fully connected, i.e. not clustered.

    Parameters
    ----------
    network : GenericNetwork
        The network whose connectivity to check.
    pores_BC : array_like (optional)
        The pore indices of boundary conditions (inlets/outlets).

    Returns
    -------
    bool
        If ``pores_BC`` is not specified, then returns ``True`` only if
        the entire network is connected to the same cluster. If
        ``pores_BC`` is given, then returns ``True`` only if all clusters
        are connected to the given boundary condition pores.
    """
    am = network.get_adjacency_matrix(fmt='lil').copy()
    temp = csgraph.connected_components(am, directed=False)[1]
    is_connected = np.unique(temp).size == 1
    # Ensure all clusters are part of pores, if given
    if not is_connected and pores_BC is not None:
        am.resize(network.Np + 1, network.Np + 1)
        pores_BC = network._parse_indices(pores_BC)
        am.rows[-1] = pores_BC.tolist()
        am.data[-1] = np.arange(network.Nt, network.Nt + len(pores_BC)).tolist()
        temp = csgraph.connected_components(am, directed=False)[1]
        is_connected = np.unique(temp).size == 1
    return is_connected


def get_spacing(network):
    r"""
    Determine the spacing along each axis of a simple cubic network

    Parameters
    ----------
    network : OpenPNM network
        The network for which spacing is desired

    Returns
    -------
    spacing : ndarray
        The spacing along each axis in the form of ``[Lx, Ly, Lz]``, where
        ``L`` is the physical dimension in the implied units (i.e. meters)

    """
    from openpnm.topotools.generators.tools import get_spacing
    d = {'node.coords': network.coords, 'edge.conns': network.conns}
    spc = get_spacing(d)
    return spc


def get_shape(network):
    r"""
    Determine the shape of each axis of a simple cubic network

    Parameters
    ----------
    network : OpenPNM network
        The network for which shape is desired

    Returns
    -------
    shape : ndarray
        The shape along each axis in the form of ``[Nx, Ny, Nz]`` where
        ``N`` is the number of pores

    """
    from openpnm.topotools.generators.tools import get_shape
    d = {'node.coords': network.coords, 'edge.conns': network.conns}
    shp = get_shape(d)
    return shp


def get_domain_area(network, inlets=None, outlets=None):
    r"""
    Determine the cross sectional area relative to the inlets/outlets.

    Parameters
    ----------
    network : GenericNetwork
        The network object containing the pore coordinates

    inlets : array_like
        The pore indices of the inlets.

    putlets : array_Like
        The pore indices of the outlets.

    Returns
    -------
    area : scalar
        The cross sectional area relative to the inlets/outlets.

    """
    if dimensionality(network).sum() != 3:
        raise Exception('The network is not 3D, specify area manually')
    inlets = network.coords[inlets]
    outlets = network.coords[outlets]
    if not iscoplanar(inlets):
        print('Detected inlet pores are not coplanar')
    if not iscoplanar(outlets):
        print('Detected outlet pores are not coplanar')
    Nin = np.ptp(inlets, axis=0) > 0
    if Nin.all():
        print('Detected inlets are not oriented along a principle axis')
    Nout = np.ptp(outlets, axis=0) > 0
    if Nout.all():
        print('Detected outlets are not oriented along a principle axis')
    hull_in = ConvexHull(points=inlets[:, Nin])
    hull_out = ConvexHull(points=outlets[:, Nout])
    if hull_in.volume != hull_out.volume:
        print('Inlet and outlet faces are different area')
    area = hull_in.volume  # In 2D: volume=area, area=perimeter
    return area


def get_domain_length(network, inlets=None, outlets=None):
    r"""
    Determine the domain length relative to the inlets/outlets.

    Parameters
    ----------
    network : GenericNetwork
        The network object containing the pore coordinates

    inlets : array_like
        The pore indices of the inlets.

    outlets : array_Like
        The pore indices of the outlets.

    Returns
    -------
    area : scalar
        The domain length relative to the inlets/outlets.

    """
    inlets = network.coords[inlets]
    outlets = network.coords[outlets]
    if not iscoplanar(inlets):
        print('Detected inlet pores are not coplanar')
    if not iscoplanar(outlets):
        print('Detected inlet pores are not coplanar')
    tree = cKDTree(data=inlets)
    Ls = np.unique(np.float64(tree.query(x=outlets)[0]))
    if not np.allclose(Ls, Ls[0]):
        print('A unique value of length could not be found')
    length = Ls[0]
    return length


def tri_to_am(tri):
    r"""
    Given a Delaunay triangulation object from Scipy's ``spatial`` module,
    converts to a sparse adjacency matrix network representation.

    Parameters
    ----------
    tri : Delaunay Triangulation Object
        This object is produced by ``scipy.spatial.Delaunay``

    Returns
    -------
    A sparse adjacency matrix in COO format.  The network is undirected
    and unweighted, so the adjacency matrix is upper-triangular and all the
    weights are set to 1.

    """
    # Create an empty list-of-list matrix
    lil = sprs.lil_matrix((tri.npoints, tri.npoints))
    # Scan through Delaunay triangulation to retrieve pairs
    indices, indptr = tri.vertex_neighbor_vertices
    for k in range(tri.npoints):
        lil.rows[k] = indptr[indices[k]:indices[k + 1]].tolist()
    # Convert to coo format
    lil.data = lil.rows  # Just a dummy array to make things work properly
    coo = lil.tocoo()
    # Set weights to 1's
    coo.data = np.ones_like(coo.data)
    # Remove diagonal, and convert to csr remove duplicates
    am = sprs.triu(A=coo, k=1, format='csr')
    # The convert back to COO and return
    am = am.tocoo()
    return am


def vor_to_am(vor):
    r"""
    Given a Voronoi tessellation object from Scipy's ``spatial`` module,
    converts to a sparse adjacency matrix network representation in COO format.

    Parameters
    ----------
    vor : Voronoi Tessellation object
        This object is produced by ``scipy.spatial.Voronoi``

    Returns
    -------
    A sparse adjacency matrix in COO format.  The network is undirected
    and unweighted, so the adjacency matrix is upper-triangular and all the
    weights are set to 1.

    """
    # Create adjacency matrix in lil format for quick matrix construction
    N = vor.vertices.shape[0]
    rc = [[], []]
    for ij in vor.ridge_dict.keys():
        row = vor.ridge_dict[ij].copy()
        # Make sure voronoi cell closes upon itself
        row.append(row[0])
        # Add connections to rc list
        rc[0].extend(row[:-1])
        rc[1].extend(row[1:])
    rc = np.vstack(rc).T
    # Make adj mat upper triangular
    rc = np.sort(rc, axis=1)
    # Remove any pairs with ends at infinity (-1)
    keep = ~np.any(rc == -1, axis=1)
    rc = rc[keep]
    data = np.ones_like(rc[:, 0])
    # Build adj mat in COO format
    M = N = np.amax(rc) + 1
    am = sprs.coo_matrix((data, (rc[:, 0], rc[:, 1])), shape=(M, N))
    # Remove diagonal, and convert to csr remove duplicates
    am = sprs.triu(A=am, k=1, format='csr')
    # The convert back to COO and return
    am = am.tocoo()
    return am


def dict_to_am(g):
    r"""
    Convert a graph dictionary into a scipy.sparse adjacency matrix in
    COO format

    Parameters
    ----------
    g : dict
        A network dictionary

    Returns
    -------
    am : sparse matrix
        The sparse adjacency matrix in COO format

    """
    edge_prefix = get_edge_prefix(g)
    node_prefix = get_node_prefix(g)
    conns = g[edge_prefix+'.conns']
    # if symmetric:
    #     conns = np.vstack((conns, np.fliplr(conns)))
    shape = [g[node_prefix+'.coords'].shape[0]]*2
    data = np.ones_like(conns[:, 0], dtype=int)
    am = sprs.coo_matrix((data, (conns[:, 0], conns[:, 1])), shape=shape)
    return am


def dict_to_im(g):
    r"""
    Convert a graph dictionary into a scipy.sparse incidence matrix in COO
    format

    Parameters
    ----------
    g : dict
        The network dictionary

    Returns
    -------
    im : sparse matrix
        The sparse incidence matrix in COO format.

    Notes
    -----
    Rows correspond to nodes and columns correspond to edges. Each column
    has 2 nonzero values indicating which 2 nodes are connected by the
    corresponding edge. Each row contains an arbitrary number of nonzeros
    whose locations indicate which edges are directly connected to the
    corresponding node.
    """
    edge_prefix = get_edge_prefix(g)
    node_prefix = get_node_prefix(g)
    conns = g[edge_prefix+'.conns']
    coords = g[node_prefix+'.coords']
    data = np.ones(2*conns.shape[0], dtype=int)
    shape = (coords.shape[0], conns.shape[0])
    temp = np.arange(conns.shape[0])
    cols = np.vstack((temp, temp)).T.flatten()
    # Could also be done using the following, if faster:
    # cols = np.linspace(0, conns.shape[0], 2*conns.shape[0], endpoint=False).astype(int)
    rows = conns.flatten()
    im = sprs.coo_matrix((data, (rows, cols)), shape=shape)
    return im


def conns_to_am(conns, shape=None, force_triu=True, drop_diag=True,
                drop_dupes=True, drop_negs=True):
    r"""
    Converts a list of connections into a Scipy sparse adjacency matrix

    Parameters
    ----------
    conns : array_like, N x 2
        The list of site-to-site connections
    shape : list, optional
        The shape of the array.  If none is given then it is taken as 1 + the
        maximum value in ``conns``.
    force_triu : bool
        If True (default), then all connections are assumed undirected, and
        moved to the upper triangular portion of the array
    drop_diag : bool
        If True (default), then connections from a site and itself are removed.
    drop_dupes : bool
        If True (default), then all pairs of sites sharing multiple connections
        are reduced to a single connection.
    drop_negs : bool
        If True (default), then all connections with one or both ends pointing
        to a negative number are removed.

    Returns
    -------
    am : ndarray
        A sparse adjacency matrix in COO format

    """
    if force_triu:  # Sort connections to [low, high]
        conns = np.sort(conns, axis=1)
    if drop_negs:  # Remove connections to -1
        keep = ~np.any(conns < 0, axis=1)
        conns = conns[keep]
    if drop_diag:  # Remove connections of [self, self]
        keep = np.where(conns[:, 0] != conns[:, 1])[0]
        conns = conns[keep]
    # Now convert to actual sparse array in COO format
    data = np.ones_like(conns[:, 0], dtype=int)
    if shape is None:
        N = conns.max() + 1
        shape = (N, N)
    am = sprs.coo_matrix((data, (conns[:, 0], conns[:, 1])), shape=shape)
    if drop_dupes:  # Convert to csr and back too coo
        am = am.tocsr()
        am = am.tocoo()
    # Perform one last check on adjacency matrix
    missing = np.where(np.bincount(conns.flatten()) == 0)[0]
    if np.size(missing) or np.any(am.col.max() < (shape[0] - 1)):
        print('Some nodes are not connected to any bonds')
    return am


def am_to_im(am):
    r"""
    Convert an adjacency matrix into an incidence matrix
    """
    if am.shape[0] != am.shape[1]:
        raise Exception('Adjacency matrices must be square')
    if am.format != 'coo':
        am = am.tocoo(copy=False)
    conn = np.vstack((am.row, am.col)).T
    row = conn[:, 0]
    data = am.data
    col = np.arange(np.size(am.data))
    if istriangular(am):
        row = np.append(row, conn[:, 1])
        data = np.append(data, data)
        col = np.append(col, col)
    im = sprs.coo.coo_matrix((data, (row, col)), (row.max() + 1, col.max() + 1))
    return im


def im_to_am(im):
    r"""
    Convert an incidence matrix into an adjacency matrix
    """
    raise Exception('This function is not implemented yet')


def istriu(am):
    r"""
    Returns ``True`` if the sparse adjacency matrix is upper triangular
    """
    if am.shape[0] != am.shape[1]:
        print('Matrix is not square, triangularity is irrelevant')
        return False
    if am.format != 'coo':
        am = am.tocoo(copy=False)
    return np.all(am.row <= am.col)


def istril(am):
    r"""
    Returns ``True`` if the sparse adjacency matrix is lower triangular
    """
    if am.shape[0] != am.shape[1]:
        print('Matrix is not square, triangularity is irrelevant')
        return False
    if am.format != 'coo':
        am = am.tocoo(copy=False)
    return np.all(am.row >= am.col)


def istriangular(am):
    r"""
    Returns ``True`` if the sparse adjacency matrix is either upper or lower
    triangular
    """
    if am.format != 'coo':
        am = am.tocoo(copy=False)
    return istril(am) or istriu(am)


def issymmetric(am):
    r"""
    A method to check if a square matrix is symmetric
    Returns ``True`` if the sparse adjacency matrix is symmetric
    """
    if am.shape[0] != am.shape[1]:
        print('Matrix is not square, symmetrical is irrelevant')
        return False
    if am.format != 'coo':
        am = am.tocoo(copy=False)
    if istril(am) or istriu(am):
        return False
    # Compare am with its transpose, element wise
    sym = ((am != am.T).size) == 0
    return sym
