# MenuTitle: RedrawPath
# encoding: utf-8
# Copyright: Michael Rafailyk, 2025, www.michaelrafailyk.com Version 1.0

__doc__ = """
Merges last added path with the nearest path into one continuous path with smooth connections.
"""

import math
from GlyphsApp import Glyphs, OFFCURVE, CURVE, LINE, GSNode
from AppKit import NSPoint

# --------------------------------------------------

# CONSTANTS

# Accuracy for finding closest path and its closest segments to merge
# Smaller value gives better accuracy but produces more computation
# Greater value will improve performance but reduce accuracy.
# Minimal recommended value is 5
CLOSEST_AREA_VIRTUAL_POINT_STEP = 10

# Align connection nodes with vectors of closest segments
# True, False
ADJUST_CONNECTIONS = True

# Maximal distance between connection nodes where new path node will be adjusted
# New path node moves to intermediate point
CONNECTION_ADJUST_MAX_DISTANCE = 50

# Maximal distance when new path connection node should collapse with closest path node
# Within this distance, new path node directly moves onto closest path node position
CONNECTION_COLLAPSE_MAX_DISTANCE = 25

# Minimal length of new path connection handle after adjusting it along closest path shape
# Smaller value provides sharper connection, greater value provides more smoothness
CONNECTION_HANDLE_MIN_LENGTH = 20

# --------------------------------------------------

# VARIABLES

# new_path = last added path, like the path just drawn with the Pencil tool
# NS1 = first connection node on new path (N = new path, S = start side)
# NS1h = inner handle of NS1
# NS2h = inner handle of NS2
# NS2 = next on-curve node after NS1
# NE2 = previous on-curve node before NE1
# NE2h = inner handle of NE2
# NE1h = inner handle of NE1
# NE1 = last connection node on new path (N = new path, E = end side)

# closest_path = existing path that is closest to new path
# closest_area = shortest side of closest path that should be replaced with new path
# CS1 = first connection node (C = closest path, S = start side)
# CE1 = last connection node (C = closest path, E = end side)
# CS_vector = original shape direction of closest start segment needed for adjustments
# CE_vector = original shape direction of closest end segment needed for adjustments

# --------------------------------------------------



# Identify connection nodes on new path
def identify_new_path_connection_nodes(path):
	nodes = path.nodes
	NS1 = nodes[0]
	NE1 = nodes[-1]
	return NS1, NE1



# Find closest area on closest path and detect nodes for connection
def identify_closest_area(paths, new_path, NS1, NE1):
	# Compute bounding box of a cubic curve segment
	def cubic_bezier_bbox(p0, p1, p2, p3):
		# Solve derivative roots in [0,1] for one axis
		def cubic_extrema(a, b, c, d):
			A = -a + 3*b - 3*c + d
			B = 2*(a - 2*b + c)
			C = b - a
			ts = []
			if abs(A) < 1e-12:
				if abs(B) > 1e-12:
					t = -C / B
					if 0 < t < 1:
						ts.append(t)
			else:
				discriminant = B*B - 4*A*C
				if discriminant >= 0:
					sqrtD = discriminant ** 0.5
					t1 = (-B + sqrtD) / (2*A)
					t2 = (-B - sqrtD) / (2*A)
					for t in [t1, t2]:
						if 0 < t < 1:
							ts.append(t)
			return ts
		# X-axis extrema
		tx = cubic_extrema(p0.x, p1.x, p2.x, p3.x)
		xs = [p0.x, p3.x] + [((1-t)**3 * p0.x + 3*(1-t)**2*t*p1.x + 3*(1-t)*t**2*p2.x + t**3*p3.x) for t in tx]
		min_x, max_x = min(xs), max(xs)
		# Y-axis extrema
		ty = cubic_extrema(p0.y, p1.y, p2.y, p3.y)
		ys = [p0.y, p3.y] + [((1-t)**3 * p0.y + 3*(1-t)**2*t*p1.y + 3*(1-t)*t**2*p2.y + t**3*p3.y) for t in ty]
		min_y, max_y = min(ys), max(ys)
		return min_x, min_y, max_x, max_y
	# Compute bounding box of any segment
	def segment_bbox(segment_nodes, segment_handles):
		# On-curve endpoints of segment
		p0 = segment_nodes[0].position
		p3 = segment_nodes[-1].position
		# Cubic curve
		if len(segment_handles) == 2:
			p1 = segment_handles[0].position
			p2 = segment_handles[1].position
			return cubic_bezier_bbox(p0, p1, p2, p3)
		# Quadratic curve
		elif len(segment_handles) == 1:
			p1 = segment_handles[0].position
			# Approximation from quadratic to cubic
			c0 = p0
			c1 = NSPoint(p0.x + 2/3*(p1.x - p0.x), p0.y + 2/3*(p1.y - p0.y))
			c2 = NSPoint(p3.x + 2/3*(p1.x - p3.x), p3.y + 2/3*(p1.y - p3.y))
			c3 = p3
			return cubic_bezier_bbox(c0, c1, c2, c3)
		# Line (or any broken segment with 3+ handles)
		else:
			xs = [n.position.x for n in segment_nodes]
			ys = [n.position.y for n in segment_nodes]
			return min(xs), min(ys), max(xs), max(ys)
	# Place virtual points along segment shape
	def segment_virtual_points(segment_nodes, segment_handles, step):
		# On-curve endpoints of segment
		p0 = segment_nodes[0].position
		p3 = segment_nodes[-1].position
		# Rough (straight-line) segment length between endpoints
		seg_length = ((p3.x - p0.x)**2 + (p3.y - p0.y)**2) ** 0.5
		num_points = max(2, int(seg_length / step) + 1)
		virtual_points = []
		# Cubic curve
		if len(segment_handles) == 2:
			p1 = segment_handles[0].position
			p2 = segment_handles[1].position
			ax = -p0.x + 3 * p1.x - 3 * p2.x + p3.x
			ay = -p0.y + 3 * p1.y - 3 * p2.y + p3.y
			bx = 3 * p0.x - 6 * p1.x + 3 * p2.x
			by = 3 * p0.y - 6 * p1.y + 3 * p2.y
			cx = -3 * p0.x + 3 * p1.x
			cy = -3 * p0.y + 3 * p1.y
			dx0, dy0 = p0.x, p0.y
			for k in range(num_points):
				t = k / (num_points - 1)
				x = ((ax * t + bx) * t + cx) * t + dx0
				y = ((ay * t + by) * t + cy) * t + dy0
				virtual_points.append((x, y))
		# Quadratic curve
		elif len(segment_handles) == 1:
			p1 = segment_handles[0].position
			for t in [k / (num_points - 1) for k in range(num_points)]:
				x = (1 - t) ** 2 * p0.x + 2 * (1 - t) * t * p1.x + t ** 2 * p3.x
				y = (1 - t) ** 2 * p0.y + 2 * (1 - t) * t * p1.y + t ** 2 * p3.y
				virtual_points.append((x, y))
		# Line (or any broken segment with 3+ handles)
		else:
			for t in [k / (num_points - 1) for k in range(num_points)]:
				x = p0.x + (p3.x - p0.x) * t
				y = p0.y + (p3.y - p0.y) * t
				virtual_points.append((x, y))
		return virtual_points
	# --------------------------------------------------
	# Find two closest segments on the same path using candidates
	best_path = None
	closest_start_segment = None
	closest_end_segment = None
	min_dist_start = float("inf")
	min_dist_end = float("inf")
	# Check all paths except new path
	for path in paths:
		if new_path is not None and path is new_path:
			continue
		nodes = path.nodes
		# For each segment
		oncurve_indices = [i for i, n in enumerate(nodes) if n.type != OFFCURVE]
		for i in range(len(oncurve_indices)):
			# Indices of first and last on-curve nodes on segment
			i1 = oncurve_indices[i]
			i2 = oncurve_indices[(i + 1) % len(oncurve_indices)]
			# Collect all segment nodes including handles
			if i1 <= i2:
				segment_nodes = nodes[i1:i2 + 1]
			else:
				segment_nodes = nodes[i1:] + nodes[:i2 + 1]
			segment_handles = [n for n in segment_nodes[1:-1] if n.type == OFFCURVE]
			# --------------------------------------------------
			# Quick distance check using bounding box of segment
			# Get bounding box
			min_x, min_y, max_x, max_y = segment_bbox(segment_nodes, segment_handles)
			# Compare distance from bounding box to NS1 and NE1
			dx = max(min_x - NS1.x, 0, NS1.x - max_x)
			dy = max(min_y - NS1.y, 0, NS1.y - max_y)
			dist_start = math.hypot(dx, dy)
			dx = max(min_x - NE1.x, 0, NE1.x - max_x)
			dy = max(min_y - NE1.y, 0, NE1.y - max_y)
			dist_end = math.hypot(dx, dy)
			# Skip segment if the best distances to NS1 and NE1 can't be improved
			if dist_start >= min_dist_start and dist_end >= min_dist_end:
				continue
			# --------------------------------------------------
			# Extended distance check by placing a virtual points along segment shape
			step = CLOSEST_AREA_VIRTUAL_POINT_STEP
			virtual_points = segment_virtual_points(segment_nodes, segment_handles, step)
			# Compare distance from each virtual point to NS1 and NE1
			for (vx, vy) in virtual_points:
				dx_s, dy_s = vx - NS1.x, vy - NS1.y
				dx_e, dy_e = vx - NE1.x, vy - NE1.y
				d_start = (dx_s**2 + dy_s**2) ** 0.5
				d_end = (dx_e**2 + dy_e**2) ** 0.5
				if d_start < min_dist_start:
					min_dist_start = d_start
					closest_start_segment = (i1, i2)
					best_path = path
				if d_end < min_dist_end:
					min_dist_end = d_end
					closest_end_segment = (i1, i2)
					best_path = path
	# --------------------------------------------------
	if best_path is None:
		return None, None, None, None, None, None, False
	# Save best closest path
	closest_path = best_path
	# --------------------------------------------------
	# Find closest area
	# Visually new path lies inside closest area
	nodes = closest_path.nodes
	total_nodes = len(nodes)
	# Allow paths with least two segments
	if total_nodes < 4:
		return None, None, None, None, None, None, False
	# Extract segment node indices
	start_seg_start, start_seg_end = closest_start_segment
	end_seg_start, end_seg_end = closest_end_segment
	# Expand a segment (inclusive), with wrap-around
	def expand_segment_indices(segment):
		s, e = segment
		if s <= e:
			return list(range(s, e + 1))
		else:
			return list(range(s, total_nodes)) + list(range(0, e + 1))
	# Build sets of indices to cover (both closest segments including off-curve nodes)
	start_pair_set = set(expand_segment_indices(closest_start_segment))
	end_pair_set   = set(expand_segment_indices(closest_end_segment))
	required_set = start_pair_set.union(end_pair_set)
	# Walk from start_index with given step until we've visited all required indices
	# Returns the visited list in walk order
	def walk_until_covered(start_index, step):
		visited = []
		seen = set()
		i = start_index
		max_steps = total_nodes * 2  # safety cap (should not be hit)
		steps = 0
		while True:
			if i not in seen:
				visited.append(i)
				seen.add(i)
			# Stop when we've covered all required nodes and we've visited at least one step
			if required_set.issubset(seen) and steps >= 0:
				break
			i = (i + step) % total_nodes
			steps += 1
			if steps > max_steps:
				break
		return visited
	# Two candidate walks
	# Forward candidate: start at the start node of the start pair, walk +1
	forward_walk = walk_until_covered(start_seg_start, 1)
	# Backward candidate: start at the end node of the start pair, walk -1
	backward_walk = walk_until_covered(start_seg_end, -1)
	# Choose the shorter candidate
	if len(forward_walk) <= len(backward_walk):
		closest_area = forward_walk
	else:
		closest_area = backward_walk
	# Geometric fallback for identical start/end segments
	if (
		closest_start_segment == closest_end_segment
		or set(expand_segment_indices(closest_start_segment)) == set(expand_segment_indices(closest_end_segment))
	):
		# Geometric fallback for identical start/end segments considering both NS1 and NE1
		# Include all nodes of the segment (off-curves too)
		seg_indices = expand_segment_indices(closest_start_segment)
		i1, i2 = seg_indices[0], seg_indices[-1]
		n1, n2 = nodes[i1], nodes[i2]
		# Compute squared distances to NS1 and NE1
		d1_to_NS1 = (n1.x - NS1.x) ** 2 + (n1.y - NS1.y) ** 2
		d2_to_NS1 = (n2.x - NS1.x) ** 2 + (n2.y - NS1.y) ** 2
		d1_to_NE1 = (n1.x - NE1.x) ** 2 + (n1.y - NE1.y) ** 2
		d2_to_NE1 = (n2.x - NE1.x) ** 2 + (n2.y - NE1.y) ** 2
		# Compare both possible orientations
		sum1 = d1_to_NS1 + d2_to_NE1
		sum2 = d2_to_NS1 + d1_to_NE1
		# Preserve all off-curve nodes, reversed if needed
		if sum2 < sum1:
			closest_area = list(reversed(seg_indices))
		else:
			closest_area = list(seg_indices)
	# --------------------------------------------------
	# Check if closest path is open and its end-start nodes lies inside closest area
	open_wraparound = False
	wrap_case = (0 in closest_area and (len(closest_path.nodes) - 1) in closest_area)
	if wrap_case and not closest_path.closed:
		open_wraparound = True
	# --------------------------------------------------
	# Save variables for next steps
	# Connection nodes
	CS1 = nodes[closest_area[0]]
	CE1 = nodes[closest_area[-1]]
	# Vectors for nodes/handles adjustment
	# Always point inward of closest area
	# Works for both smooth and corner nodes, including line-only areas
	def vector_from_nodes(a, b):
		return (b.x - a.x, b.y - a.y)
	if len(closest_area) >= 3:
		# Closest internal nodes of new path
		CS0 = closest_path.nodes[closest_area[1]]
		CE0 = closest_path.nodes[closest_area[-2]]
		# Start and end vector
		CS_vector = vector_from_nodes(CS1, CS0)
		CE_vector = vector_from_nodes(CE1, CE0)
	else:
		# Closest area is a line
		CS_vector = vector_from_nodes(CS1, CE1)
		CE_vector = vector_from_nodes(CE1, CS1)
	return closest_path, closest_area, CS1, CE1, CS_vector, CE_vector, open_wraparound



# Ensure new path follow the same direction as closest path
def sync_paths_directions(closest_path, closest_area, new_path, CS1, CE1, CS_vector, CE_vector):
	# For the closest path, determine direction using first two indices of the closest area
	closest_path_length = len(closest_path.nodes)
	forward_distance = (closest_area[1] - closest_area[0]) % closest_path_length
	backward_distance = (closest_area[0] - closest_area[1]) % closest_path_length
	closest_path_forward = forward_distance < backward_distance
	# For the new path, NS1-NE1 is always considered forward
	new_path_forward = True
	# If new path direction is opposite to closest path direction
	if not closest_path_forward == new_path_forward:
		# --------------------------------------------------
		# Reverse new path to align its direction with closest path
		new_path.reverse()
		# Swap closest path references respectively
		closest_area.reverse()
		CS1, CE1 = CE1, CS1
		CS_vector, CE_vector = CE_vector, CS_vector
	return closest_area, new_path, CS1, CE1, CS_vector, CE_vector



# Merge closest and new paths
def merge_paths(layer, closest_path, closest_area, CS1, new_path):
	# Remove closest area on closest path except connection nodes
	nodes_to_remove = [closest_path.nodes[i] for i in closest_area[1:-1]]
	for n in nodes_to_remove:
		closest_path.removeNode_(n)
	# --------------------------------------------------
	# Fix CE1 (last node in closest area) node type if originally it wasn't LINE
	# After removing nodes, CS1-CE1 becomes line segment, so CE1 type should be updated
	num_nodes = len(closest_path.nodes)
	idx_CS1 = closest_path.nodes.index(CS1)
	idx_CE1 = (idx_CS1 + 1) % num_nodes
	CE1_temporary = closest_path.nodes[idx_CE1]
	if CE1_temporary.type != LINE:
		CE1_temporary.type = LINE
	# --------------------------------------------------
	# Inserts nodes from new path immediately after CS1
	CS1_index = closest_path.nodes.index(CS1)
	inserted_nodes = []
	for offset, n in enumerate(new_path.nodes):
		new_node = GSNode(n.position, n.type)
		closest_path.insertNode_atIndex_(new_node, CS1_index + 1 + offset)
		inserted_nodes.append(new_node)
		new_node.smooth = n.smooth
	# --------------------------------------------------
	# Remove temporary new path
	layer.removeShape_(new_path)
	# --------------------------------------------------
	# Re-identify all key nodes of new path after the merge
	NS1 = inserted_nodes[0]
	NS1h = inserted_nodes[1] if len(inserted_nodes) > 1 else None
	NS2h = inserted_nodes[2] if len(inserted_nodes) > 2 else None
	NS2 = inserted_nodes[3] if len(inserted_nodes) > 3 else None
	NE2 = inserted_nodes[-4] if len(inserted_nodes) > 3 else None
	NE2h = inserted_nodes[-3] if len(inserted_nodes) > 2 else None
	NE1h = inserted_nodes[-2] if len(inserted_nodes) > 1 else None
	NE1 = inserted_nodes[-1]
	return NS1, NS1h, NS2h, NS2, NE1, NE1h, NE2h, NE2



# Adjust new path connection nodes and handles to preserve existing path smothness
def adjust_connections(NS1, NS1h, NE1, NE1h, CS1, CE1, CS_vector, CE_vector, closest_path):
	def adjust_pair(N1, N1h, O1, vector):
		# Vector verification and normalization
		if vector is None:
			return
		vector_x, vector_y = vector
		vector_length = math.hypot(vector_x, vector_y)
		if vector_length == 0:
			return
		# Normalized vector direction
		unit_x, unit_y = vector_x / vector_length, vector_y / vector_length
		# --------------------------------------------------
		# Calculate target positions for N1 nodes
		# Project N1 onto vector of O so all nodes now on same virtual line
		origin_x, origin_y = O1.x, O1.y
		projection_length = (N1.x - origin_x) * unit_x + (N1.y - origin_y) * unit_y
		projection_x = origin_x + projection_length * unit_x
		projection_y = origin_y + projection_length * unit_y
		# Measure distance from projected N to O
		offset_x, offset_y = origin_x - projection_x, origin_y - projection_y
		distance = math.hypot(offset_x, offset_y)
		# Limit distance if it is greater than adjustment range
		if distance > CONNECTION_ADJUST_MAX_DISTANCE:
			offset_x /= distance
			offset_y /= distance
			origin_x = projection_x + offset_x * CONNECTION_ADJUST_MAX_DISTANCE
			origin_y = projection_y + offset_y * CONNECTION_ADJUST_MAX_DISTANCE
			distance = CONNECTION_ADJUST_MAX_DISTANCE
		# Midpoint position between N and O (or limited O) nodes
		N1_target_x = (projection_x + origin_x) / 2.0
		N1_target_y = (projection_y + origin_y) / 2.0
		# --------------------------------------------------
		# Calculate target position for handle (projection-based)
		if N1h is not None and N1h.type == OFFCURVE:
			# Project N1h handle onto the same vector of O
			N1h_proj_length = (N1h.x - O1.x) * unit_x + (N1h.y - O1.y) * unit_y
			N1h_proj_x = O1.x + N1h_proj_length * unit_x
			N1h_proj_y = O1.y + N1h_proj_length * unit_y
			# Measure distance from N1 to projected N1h
			handle_distance = (N1h_proj_x - N1_target_x) * unit_x + (N1h_proj_y - N1_target_y) * unit_y
			# Ensure the handle lies on the correct side
			if handle_distance < 0:
				handle_distance = 0
			# Apply minimum handle length rule
			if handle_distance < CONNECTION_HANDLE_MIN_LENGTH:
				handle_distance = CONNECTION_HANDLE_MIN_LENGTH
			# Compute handle target along the same O1-N1-N1h line
			N1h_target_x = N1_target_x + unit_x * handle_distance
			N1h_target_y = N1_target_y + unit_y * handle_distance
		# --------------------------------------------------
		if distance <= CONNECTION_COLLAPSE_MAX_DISTANCE:
			# Move new path connection node directly to O1 position
			N1.x, N1.y = O1.x, O1.y
			# Remove O1 (closest path connection node) after collapse
			closest_path.removeNodeCheckKeepShape_normalizeHandles_(O1, True)
			# Make new path connection node smooth if closest path connection node was smooth
			if N1h is not None and O1.smooth:
				N1.smooth = True
		else:
			# Move new path connection node to intermediate position
			N1.x, N1.y = N1_target_x, N1_target_y
			# Make new path connection node smooth
			if N1h is not None:
				N1.smooth = True
		if N1h is not None and N1h.type == OFFCURVE:
			# Move new path connection handle
			N1h.x, N1h.y = N1h_target_x, N1h_target_y
	# --------------------------------------------------
	# Apply to both sides
	adjust_pair(NS1, NS1h, CS1, CS_vector)
	adjust_pair(NE1, NE1h, CE1, CE_vector)



# Adjust connection handles to avoid loops or inflections
def normalize_connections_handles(NS1, NS1h, NS2h, NS2, NE1, NE1h, NE2h, NE2):
	# Start side
	if NS1h is not None and NS2h is not None:
		if NS1h.type == OFFCURVE and NS2h.type == OFFCURVE:
			shorten_inflected_handles_on_segment(NS1, NS1h, NS2h, NS2)
	# End side
	if NE1h is not None and NE2h is not None:
		if NE1h.type == OFFCURVE and NE2h.type == OFFCURVE:
			shorten_inflected_handles_on_segment(NE2, NE2h, NE1h, NE1)



# Shorten handles (on segment) that have a loop or inflection
# THIS IS A COPY OF FUNCTION FROM SIMPLIFY PATH SCRIPT
def shorten_inflected_handles_on_segment(n1, h1, h2, n2):
	INTERSECTION_MIN_LENGTH = 1
	INTERSECTION_BUFFER = 1
	INFLECTION_MIN_ANGLE = 45
	INFLECTION_HANDLE_MIN_LENGTH = 1
	# Skip segments with collapsed nodes or zero handles
	seg_len = math.hypot(n2.x - n1.x, n2.y - n1.y)
	h1_len = math.hypot(h1.x - n1.x, h1.y - n1.y)
	h2_len = math.hypot(h2.x - n2.x, h2.y - n2.y)
	if seg_len == 0 or h1_len == 0 or h2_len == 0:
		return
	# --------------------------------------------------
	# Intersection case
	# Check inflection (single intersection)
	# Check loop (double intersection)
	def intersection_of_vectors(n1, h1, n2, h2):
		x1, y1 = n1.x, n1.y
		x2, y2 = h1.x, h1.y
		x3, y3 = n2.x, n2.y
		x4, y4 = h2.x, h2.y
		det = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
		if det == 0:
			return None
		px = ((x1 * y2 - y1 * x2) * (x3 - x4) - (x1 - x2) * (x3 * y4 - y3 * x4)) / det
		py = ((x1 * y2 - y1 * x2) * (y3 - y4) - (y1 - y2) * (x3 * y4 - y3 * x4)) / det
		return (px, py)
	interpoint = intersection_of_vectors(n1, h1, n2, h2)
	intersection = False
	dist1 = dist2 = None
	if interpoint is not None:
		# Check if both handles tips are exactly in the same coordinate
		if (h1.x, h1.y) == (h2.x, h2.y):
			intersection = True
			dist1 = max(0, h1_len - INTERSECTION_BUFFER)
			dist2 = max(0, h2_len - INTERSECTION_BUFFER)
		else:
			# Check vectors and distances
			v1_to_inter = (interpoint[0] - n1.x, interpoint[1] - n1.y)
			v2_to_inter = (interpoint[0] - n2.x, interpoint[1] - n2.y)
			v1_dir = (h1.x - n1.x, h1.y - n1.y)
			v2_dir = (h2.x - n2.x, h2.y - n2.y)
			# Check if intersection is on front side (between nodes)
			dist1 = max(0, math.hypot(v1_to_inter[0], v1_to_inter[1]) - INTERSECTION_BUFFER)
			dist2 = max(0, math.hypot(v2_to_inter[0], v2_to_inter[1]) - INTERSECTION_BUFFER)
			dot1 = v1_to_inter[0]*v1_dir[0] + v1_to_inter[1]*v1_dir[1]
			dot2 = v2_to_inter[0]*v2_dir[0] + v2_to_inter[1]*v2_dir[1]
			# Check if at least one handle overshot the vector of other handle
			# Skip the case when handle tip lies on vector of other handle but not overshot it
			if (dot1 > 0 and dot2 > 0) and ((dist1 + INTERSECTION_BUFFER) < h1_len or (dist2 + INTERSECTION_BUFFER) < h2_len):
				# One or both handles have intersection on the front side
				intersection = True
	if intersection:
		# Shorten handles that go beyond intersection point
		# Check first handle
		if dist1 < h1_len and h1_len > INTERSECTION_MIN_LENGTH:
			new_len = max(dist1, INTERSECTION_MIN_LENGTH)
			vx, vy = h1.x - n1.x, h1.y - n1.y
			vlen = math.hypot(vx, vy)
			if vlen != 0:
				# Handle has intersection, correct it
				h1.x = n1.x + vx / vlen * new_len
				h1.y = n1.y + vy / vlen * new_len
		# Check second handle
		if dist2 < h2_len and h2_len > INTERSECTION_MIN_LENGTH:
			new_len = max(dist2, INTERSECTION_MIN_LENGTH)
			vx, vy = h2.x - n2.x, h2.y - n2.y
			vlen = math.hypot(vx, vy)
			if vlen != 0:
				# Handle has intersection, correct it
				h2.x = n2.x + vx / vlen * new_len
				h2.y = n2.y + vy / vlen * new_len
	# --------------------------------------------------
	# No intersection case
	# Check S-like inflection (almost parallel handles turned towards each other)
	else:
		# Find angle between handles
		v1x, v1y = h1.x - n1.x, h1.y - n1.y
		v2x, v2y = h2.x - n2.x, h2.y - n2.y
		dot = v1x * v2x + v1y * v2y
		cos_angle = max(-1, min(1, dot / (h1_len * h2_len)))
		angle_deg = math.degrees(math.acos(cos_angle))
		# Detect handles pointing nearly opposite
		if angle_deg > 180 - INFLECTION_MIN_ANGLE:
			# Calculate distances
			h1_n1 = math.hypot(h1.x - n1.x, h1.y - n1.y)
			h2_n1 = math.hypot(h2.x - n1.x, h2.y - n1.y)
			h1_n2 = math.hypot(h1.x - n2.x, h1.y - n2.y)
			h2_n2 = math.hypot(h2.x - n2.x, h2.y - n2.y)
			# Threshold for ignoring equal distances
			THRESHOLD = 1.0
			# Check if handles are closer to their own nodes
			h1_closer_to_own = (h1_n1 - THRESHOLD) < h2_n1
			h2_closer_to_own = (h2_n2 - THRESHOLD) < h1_n2
			if not h1_closer_to_own or not h2_closer_to_own:
				# Get segment vector
				ux, uy = (n2.x - n1.x) / seg_len, (n2.y - n1.y) / seg_len
				# Project each handle onto n1-n2 axis
				def project_along_segment(px, py):
					return (px - n1.x) * ux + (py - n1.y) * uy
				n1_pos = 0
				n2_pos = seg_len
				h1_pos = project_along_segment(h1.x, h1.y)
				h2_pos = project_along_segment(h2.x, h2.y)
				# Project midpoint between handles onto n1-n2 axis
				mid_x = (h1.x + h2.x) / 2.0
				mid_y = (h1.y + h2.y) / 2.0
				mid_pos = project_along_segment(mid_x, mid_y)
				# New handles lengths (could be positive or negative at this step)
				h1_new_len = mid_pos - n1_pos
				h2_new_len = n2_pos - mid_pos
				# Shorten distances so the handles will not collapse after adjustment
				h1_new_len -= INTERSECTION_BUFFER
				h2_new_len -= INTERSECTION_BUFFER
				# Balance the handles if they appear out of segment axis
				# Enforce minimum length by shifting both lengths
				if h1_new_len < INFLECTION_HANDLE_MIN_LENGTH:
					diff = INFLECTION_HANDLE_MIN_LENGTH - h1_new_len
					h1_new_len = INFLECTION_HANDLE_MIN_LENGTH
					h2_new_len -= diff
				if h2_new_len < INFLECTION_HANDLE_MIN_LENGTH:
					diff = INFLECTION_HANDLE_MIN_LENGTH - h2_new_len
					h2_new_len = INFLECTION_HANDLE_MIN_LENGTH
					h1_new_len -= diff
				# Protect the handles from being zero width or falling behind its node
				h1_new_len = max(h1_new_len, INFLECTION_HANDLE_MIN_LENGTH)
				h2_new_len = max(h2_new_len, INFLECTION_HANDLE_MIN_LENGTH)
				# Adjust handles
				h1.x = n1.x + ((v1x / h1_len) * h1_new_len)
				h1.y = n1.y + ((v1y / h1_len) * h1_new_len)
				h2.x = n2.x + ((v2x / h2_len) * h2_new_len)
				h2.y = n2.y + ((v2y / h2_len) * h2_new_len)



# Redraw Path controller
def redraw_path(layer, paths, new_path, adjustConnections):
	# Use passed constants if provided, otherwise fall back to default constants
	if adjustConnections is None:
		adjustConnections = ADJUST_CONNECTIONS
	# Identify connection nodes on new path
	(
		NS1, NE1
	) = identify_new_path_connection_nodes(new_path)
	# Find closest area on closest path and detect nodes for connection
	(
		closest_path, closest_area, CS1, CE1, CS_vector, CE_vector, open_wraparound
	) = identify_closest_area(paths, new_path, NS1, NE1)
	# Stop the process if closest path is not found
	if closest_path is None:
		return
	# Close closed path if it's open and its end-start nodes lies inside closest area
	if open_wraparound:
		closest_path.closed = True
	# Ensure new path follow the same direction as closest path
	(
		closest_area, new_path, CS1, CE1, CS_vector, CE_vector
	) = sync_paths_directions(closest_path, closest_area, new_path, CS1, CE1, CS_vector, CE_vector)
	# Merge closest and new paths
	(
		NS1, NS1h, NS2h, NS2, NE1, NE1h, NE2h, NE2
	) = merge_paths(layer, closest_path, closest_area, CS1, new_path)
	# Adjust connections (optional, controlled by plugin settings in View menu)
	if adjustConnections:
		# Adjust new path connection nodes and handles to preserve path smothness
		adjust_connections(NS1, NS1h, NE1, NE1h, CS1, CE1, CS_vector, CE_vector, closest_path)
		# Adjust connection handles to avoid loops or inflections
		normalize_connections_handles(NS1, NS1h, NS2h, NS2, NE1, NE1h, NE2h, NE2)
	else:
		# Make sure connection nodes of existing path are not smooth
		CS1.smooth = False
		CE1.smooth = False



# Run as a standalone script only if not imported from a plugin
if __name__ == "__main__":
	Glyphs.font.disableUpdateInterface()
	try:
		# Process last added path
		layer = Glyphs.font.selectedLayers[0]
		paths = [p for p in layer.paths if p.nodes]
		# Make sure there are at least two paths to merge
		if len(paths) >= 2:
			redraw_path(layer, paths, paths[-1], ADJUST_CONNECTIONS)
	except Exception as e:
		print("Error in Redraw Path:", e)
	finally:
		Glyphs.font.enableUpdateInterface()
		Glyphs.redraw()
