# MenuTitle: Simplify Path
# encoding: utf-8
# Copyright: Michael Rafailyk, 2025, www.michaelrafailyk.com Version 1.0

__doc__ = """
Simplifies selected path or all paths on selected layer by smoothing out ripples, removing tight nodes, and fixing degraded or inflected handles.
"""

import math
from GlyphsApp import OFFCURVE, CURVE, LINE

# --------------------------------------------------

# CONSTANTS

# Maximum angle tolerance in which almost straight sequences will be adjusted onto their average vectors
# Recommended range: 0-30 degrees
SMOOTH_OUT_RIPPLES_ANGLE = 10

# Nodes that lies closer to each other than a threshold, will be removed
# Smaller value gives more accuracy, greater value gives more smoothness
TIGHT_NODES_THRESHOLD = 10

# Maximal angle (between three on-curve nodes) on shape turns when the node will be preserved
# Smaller angle gives more smoothness (preserve more nodes), greater angle gives more accuracy
# Recommended range: 60-120 degrees
TIGHT_NODES_TURNS_ANGLE = 90

# Minimal handle length after pulling zero/turned-backward/rotated handle out from node
# Minimum value should be 1, greater value gives more smoothness
DEGRADED_HANDLE_MIN_LENGTH = 2

# Maximum angle tolerance when handle and opposite handle/node are facing same or opposite direction
# Normally, when handle turned backward, angle is 0, and if is opposed to opposite, angle is 180
# Recommended range: 0-45 degrees
DEGRADED_HANDLE_ANGLE_TOLERANCE = 30

# Minimal handle length after fixing inflection of handles on the same segment
# Double intersection = loop, single intersection = inflection, non-intersection = S-like inflection
# Minimum value should be 1 to avoid handle collapsing with its node
INFLECTION_HANDLE_MIN_LENGTH = 1

# Minimal distance from handle to intersection point after fixing inflection
# If distance is 0, two handles may collapse in the intersection point
INFLECTION_BUFFER = 1

# Minimal angle to fix S-like inflection when no handle intersects vector of its partner
# 180 degree is continuous parallel handles looking into each other
# 90 degree is perpendicular handles
# Recommended range: 135-180 degrees
INFLECTION_S_MIN_ANGLE = 135

# --------------------------------------------------



# Smooth out ripples on almost straight sequences
def smooth_out_ripples(path):
	nodes = path.nodes
	node_count = len(nodes)
	if node_count < 3:
		return
	# --------------------------------------------------
	# Collect sequences
	def collect_sequences():
		# Vector between segments
		def vector_between(nA, nB):
			return (nB.x - nA.x, nB.y - nA.y)
		# Angle between segments
		def angle_between(v1, v2):
			dot = v1[0]*v2[0] + v1[1]*v2[1]
			mag = math.hypot(v1[0], v1[1]) * math.hypot(v2[0], v2[1])
			if mag == 0:
				return 0
			cosang = max(min(dot / mag, 1), -1)
			return abs(math.degrees(math.acos(cosang)))
		# Save sequence
		def save_sequence(current_oncurves):
			# Nodes/handles to adjust
			adjust_from = current_oncurves[1]
			adjust_to = current_oncurves[-2]
			if nodes[adjust_from - 1].type == OFFCURVE:
				adjust_from -= 1
			if nodes[adjust_to + 1].type == OFFCURVE:
				adjust_to += 1
			adjust = list(range(adjust_from, adjust_to + 1))
			# Nodes to remove
			if len(current_oncurves) >= 5:
				remove = current_oncurves[2:-2]
			else:
				remove = []
			# Save sequence
			sequences.append({
				"node_from": nodes[adjust_from],
				"node_to": nodes[adjust_to],
				"adjust": adjust,
				"remove": remove,
			})
		# --------------------------------------------------
		# Data to return
		sequences = []
		# Data to compare
		last_vector = None
		current_start = None
		current_oncurves = []
		# Check each segment
		for i in range(node_count - 1):
			# Segment could be either line or curve
			nA = nodes[i]
			if nA.type == OFFCURVE:
				continue
			if i + 1 < node_count and nodes[i + 1].type != OFFCURVE:
				nB = nodes[i + 1]
				nB_index = i + 1
			elif i + 3 < node_count and nodes[i + 3].type != OFFCURVE:
				nB = nodes[i + 3]
				nB_index = i + 3
			else:
				continue
			# Compute node-node vector
			v = vector_between(nA, nB)
			# --------------------------------------------------
			# Start new sequence
			if current_start is None:
				current_start = i
				last_vector = v
				# Store on-curve indices of segment
				current_oncurves = [i, nB_index]
				continue
			# Check if still straight-ish
			angle = angle_between(last_vector, v)
			if angle <= SMOOTH_OUT_RIPPLES_ANGLE:
				# Continues sequence
				last_vector = v
				# Only append the new on-curve node if not duplicate
				if current_oncurves[-1] != nB_index:
					current_oncurves.append(nB_index)
			else:
				# End sequence
				# Should contain at least three segments
				if len(current_oncurves) >= 4:
					save_sequence(current_oncurves)
				# Start new sequence beginning at this node
				current_start = i
				last_vector = v
				current_oncurves = [i, nB_index]
		# Close final sequence at end of path
		if current_start is not None and len(current_oncurves) >= 4:
			save_sequence(current_oncurves)
		# Return all sequences
		return sequences
	# --------------------------------------------------
	# Adjust sequences to their vectors
	def adjust_nodes(sequences):
		for sequence in sequences:
			# Average vector for adjusted nodes
			ABx = sequence["node_to"].x - sequence["node_from"].x
			ABy = sequence["node_to"].y - sequence["node_from"].y
			AB_len_squared = ABx**2 + ABy**2
			if AB_len_squared == 0:
				return
			# Place each inner node perpendicularly on the average vector
			for i in sequence["adjust"][1:-1]:
				node = nodes[i]
				# Node projection onto the vector
				APx = node.x - sequence["node_from"].x
				APy = node.y - sequence["node_from"].y
				t = (APx*ABx + APy*ABy) / AB_len_squared
				proj_x = sequence["node_from"].x + t * ABx
				proj_y = sequence["node_from"].y + t * ABy
				# Move node
				node.x = proj_x
				node.y = proj_y
	# --------------------------------------------------
	# Remove inner redundant nodes (except two outer ones that are not in this list)
	def remove_nodes(sequences):
		indices = []
		for sequence in sequences:
			indices.extend(sequence["remove"])
		# Remove nodes in reversed order
		indices.reverse()
		for i in indices:
			path.removeNodeCheckKeepShape_normalizeHandles_(nodes[i], True)
	# --------------------------------------------------
	# Merge left two nodes into one and move it to the center of sequence
	def merge_and_center_nodes(sequences):
		# Process sequences in reversed order
		for sequence in reversed(sequences):
			n1 = sequence["node_from"]
			n2 = sequence["node_to"]
			i1 = nodes.index(n1)
			i2 = nodes.index(n2)
			if i2 - i1 < 3:
				return
			# Remove inner nodes manually
			# If from/to are handles, removal will produce one smooth node
			# If from/to are nodes, removal will produce line segment
			remove_from = i1 + 1
			center_node = False
			if n1.type == OFFCURVE and n2.type == OFFCURVE:
				remove_from = i1 + 2
				center_node = True
			indices_to_remove = list(range(remove_from, i2))
			for i in reversed(indices_to_remove):
				path.removeNode_(nodes[i])
			# Update "to" node type if it was a curve
			if n2.type == CURVE:
				n2.type = LINE
				n2.smooth = False
			# Center left smooth node to the middle of sequence
			if center_node:
				node = nodes[i1 + 1]
				target_x = n1.x + (n2.x - n1.x) / 2
				target_y = n1.y + (n2.y - n1.y) / 2
				node.x, node.y = target_x, target_y
	# --------------------------------------------------
	# Collect sequences
	sequences = collect_sequences()
	# Adjust sequences to their average vectors
	adjust_nodes(sequences)
	# Remove inner redundant nodes on sequences
	remove_nodes(sequences)
	# Merge left two nodes into one and move it to the center of sequence
	merge_and_center_nodes(sequences)



# Remove tight nodes
# Remove nodes that lies too close in range of distance and angle thresholds except smooth extremes
def remove_tight_nodes(path):
	threshold = TIGHT_NODES_THRESHOLD
	nodes = path.nodes
	protected_nodes = set()
	# --------------------------------------------------
	# Protect pass
	# Collect protected nodes (smooth extremes + sharp turns of shape)
	def collect_protected_nodes():
		path_length = len(nodes)
		for i in range(1, path_length - 1):
			node = nodes[i]
			if node.type == OFFCURVE:
				continue
			# Find previous/next on-curve nodes and handles
			prev = None
			next = None
			prev_prev_handle = None
			prev_next_handle = None
			if i - 1 >= 0 and nodes[i - 1].type != OFFCURVE:
				prev = nodes[i - 1]
			elif i - 3 >= 0 and nodes[i - 3].type != OFFCURVE:
				prev = nodes[i - 3]
				if i - 4 >= 0 and nodes[i - 4].type == OFFCURVE:
					prev_prev_handle = nodes[i - 4]
				prev_next_handle = nodes[i - 2]
			if i + 1 < path_length and nodes[i + 1].type != OFFCURVE:
				next = nodes[i + 1]
			elif i + 3 < path_length and nodes[i + 3].type != OFFCURVE:
				next = nodes[i + 3]
			if not (prev and next):
				continue
			# Distance between each on-curve pair
			dist_prev = math.hypot(prev.x - node.x, prev.y - node.y)
			dist_next = math.hypot(next.x - node.x, next.y - node.y)
			if not (dist_prev < threshold or dist_next < threshold):
				continue
			# --------------------------------------------------
			# Smooth extreme protection
			# Check if node has two handles
			prev_handle = None
			next_handle = None
			if i - 1 >= 0 and nodes[i - 1].type == OFFCURVE:
				prev_handle = nodes[i - 1]
			if i + 1 < path_length and nodes[i + 1].type == OFFCURVE:
				next_handle = nodes[i + 1]
			if prev_handle is not None and next_handle is not None:
				# Check if node is smooth extreme (node and both its handles lie on the same axis)
				node_on_x_axis = prev_handle.y == node.y == next_handle.y
				node_on_y_axis = prev_handle.x == node.x == next_handle.x
				if node_on_x_axis or node_on_y_axis:
					# Check if previous node also lies on the same axis
					prev_match_on_x_axis = prev.y == node.y if prev is not prev_handle else False
					prev_match_on_y_axis = prev.x == node.x if prev is not prev_handle else False
					# Check if previous node handles are turned the same direction
					prev_on_x_axis = False
					prev_on_y_axis = False
					if prev_prev_handle is not None and prev_next_handle is not None:
						prev_on_x_axis = prev_prev_handle.y == prev.y == prev_next_handle.y
						prev_on_y_axis = prev_prev_handle.x == prev.x == prev_next_handle.x
					# Check if node not lies between its neighbors on another axis
					# Protect only actual extreme on shape edge, not an intermediate on axis twist
					node_is_extreme = True
					if node_on_x_axis:
						if min(prev.y, next.y) < node.y < max(prev.y, next.y):
							node_is_extreme = False
					elif node_on_y_axis:
						if min(prev.x, next.x) < node.x < max(prev.x, next.x):
							node_is_extreme = False
					# Check if node is a first extreme on axis in a threshold range
					# Protect only first extreme node on axis
					first_extreme_on_axis = True
					if dist_prev < threshold:
						first_extreme_on_axis = (
							(node_on_x_axis and not (prev_match_on_x_axis and prev_on_x_axis))
							or
							(node_on_y_axis and not (prev_match_on_y_axis and prev_on_y_axis))
						)
					# Do not protect pre-last extreme on a short last segment
					if dist_next < threshold and next.index == path_length - 1:
						first_extreme_on_axis = False
					# Add node to protection set
					if node_is_extreme and first_extreme_on_axis:
						protected_nodes.add(node)
						continue
			# --------------------------------------------------
			# Sharp turn of shape protection
			# Node is not collapsed with a previous or next node
			if dist_prev < 1 or dist_next < 1:
				continue
			dot = (prev.x - node.x) * (next.x - node.x) + (prev.y - node.y) * (next.y - node.y)
			cos_angle = max(-1, min(1, dot / (dist_prev * dist_next)))
			angle_deg = math.degrees(math.acos(cos_angle))
			# Add nodes in threshold to protection set
			if angle_deg < TIGHT_NODES_TURNS_ANGLE:
				if dist_prev < threshold:
					protected_nodes.add(prev)
				protected_nodes.add(node)
				if dist_next < threshold:
					protected_nodes.add(next)
	# --------------------------------------------------
	# Cleanup pass
	# Check all nodes except first and last, in two passes
	def pass_cleanup(triplet=True):
		# Loop is reversed so nodes can be removed without affecting unchecked yet nodes
		# Check actual length of nodes instead of path length
		# Because each removal changes the path length
		for i in reversed(range(1, len(nodes) - 1)):
			node = nodes[i]
			# Check on-curve nodes that are not protected
			if node.type == OFFCURVE or node in protected_nodes:
				continue
			# Find previous/next on-curve neighbours
			prev = None
			next = None
			if i - 1 >= 0 and nodes[i - 1].type != OFFCURVE:
				prev = nodes[i - 1]
			elif i - 3 >= 0 and nodes[i - 3].type != OFFCURVE:
				prev = nodes[i - 3]
			if i + 1 < len(nodes) and nodes[i + 1].type != OFFCURVE:
				next = nodes[i + 1]
			elif i + 3 < len(nodes) and nodes[i + 3].type != OFFCURVE:
				next = nodes[i + 3]
			if not (prev and next):
				continue
			# Distance between each pair
			dist_prev = math.hypot(prev.x - node.x, prev.y - node.y)
			dist_next = math.hypot(next.x - node.x, next.y - node.y)
			# Pass 1 — Check middle node in a triplet prev-node-next
			if triplet:
				if not (dist_prev < threshold and dist_next < threshold):
					continue
			# Pass 2 — Check node in any pair prev-node or node-next
			else:
				if not (dist_prev < threshold or dist_next < threshold):
					continue
			# Remove node
			path.removeNodeCheckKeepShape_normalizeHandles_(node, True)
	# --------------------------------------------------
	# Pass 1 — Collect protected nodes
	collect_protected_nodes()
	# Pass 2 — Remove middle node in tight triplets first
	pass_cleanup(triplet=True)
	# Pass 3 — Remove any node in tight duplets remained after the triplet pass
	pass_cleanup(triplet=False)



# Fix degraded handles
# Fix zero/turned-backward/rotated handles by pulling them out from node to inner side of segment
def fix_degraded_handles(path):
	# Check handle and find its best position
	def check_handle(path, prev, opposite, node, handle, partner, next):
		# Node naming map for 3 possible cases
		# [prev - offcurve - opposite - node] [node - handle - partner - next] (curve-curve segments)
		# [opposite - node] [node - handle - partner - next] (line-curve segments)
		# [node - handle - partner - next] (curve segment, first or last on the path)
		# --------------------------------------------------
		# Angle between three nodes
		def angle_between(n1, subject, n2):
			dir_n1 = (n1.x - subject.x, n1.y - subject.y)
			dir_n2 = (n2.x - subject.x, n2.y - subject.y)
			len_n1 = math.hypot(*dir_n1)
			len_n2 = math.hypot(*dir_n2)
			if len_n1 == 0 or len_n2 == 0:
				return None
			dot = dir_n1[0] * dir_n2[0] + dir_n1[1] * dir_n2[1]
			cos = max(-1, min(1, dot / (len_n1 * len_n2)))
			return math.degrees(math.acos(cos))
		# Check if node/handle lies before the start of n1-n2 vector
		def if_turned_backward(n1, subject, n2):
			dir_segment = (n2.x - n1.x, n2.y - n1.y)
			dir_subject = (subject.x - n1.x, subject.y - n1.y)
			len_segment = math.hypot(*dir_segment)
			len_subject = math.hypot(*dir_subject)
			if len_segment == 0 or len_subject == 0:
				return False
			dot = dir_segment[0]*dir_subject[0] + dir_segment[1]*dir_subject[1]
			cos = dot / (len_segment * len_subject)
			return cos < 0
		# --------------------------------------------------
		# Check if correction required
		handle_length = math.hypot(handle.x - node.x, handle.y - node.y)
		handle_turned_backward = if_turned_backward(node, handle, next)
		handle_turned_to_opposite = False
		handles_smooth = False
		opposite_length = 0
		opposite_turned_backward = False
		opposite_isnot_on_segment = True
		if opposite is not None:
			opposite_length = math.hypot(node.x - opposite.x, node.y - opposite.y)
			if not opposite_length < 1 and not handle_length < 1:
				opposite_node_handle_angle = angle_between(opposite, node, handle)
				tolerance = DEGRADED_HANDLE_ANGLE_TOLERANCE
				# Check if handles are pointed in opposite direction (~180 degrees)
				if 180 - opposite_node_handle_angle < tolerance:
					handles_smooth = True
				# Check if handle is turned to opposite handle (or previous node)
				if opposite_node_handle_angle < tolerance and handle_turned_backward:
					handle_turned_to_opposite = True
			# Check if opposite is turned backward of its segment
			if not opposite_length < 1 and prev is not None:
				opposite_turned_backward = if_turned_backward(node, opposite, prev)
			# Check if opposite is not turned forward to current segment
			opposite_isnot_on_segment = if_turned_backward(node, opposite, next)
		# Skip normal handles
		if not (handle_length < 1 or handle_turned_backward or handle_turned_to_opposite):
			return
		# Skip if node is smooth, has correct opposed handles and opposite handle is normal
		if node.smooth and handles_smooth and handle_turned_backward and not opposite_turned_backward:
			return
		# Distances
		partner_length = math.hypot(partner.x - next.x, partner.y - next.y)
		node_partner_length = math.hypot(partner.x - node.x, partner.y - node.y)
		segment_length = math.hypot(next.x - node.x, next.y - node.y)
		partner_is_within_segment = partner_length > 0 and partner_length < segment_length
		# --------------------------------------------------
		# Align handle with opposite handle (or previous node)
		if node.smooth and opposite is not None:
			if node_partner_length >= 2 and partner_is_within_segment:
				# Target length is halfway to partner
				target_length = max(DEGRADED_HANDLE_MIN_LENGTH, node_partner_length / 2)
			else:
				# Target length is 1/3 of segment length
				target_length = max(DEGRADED_HANDLE_MIN_LENGTH, segment_length / 3)
			# Get best vector
			if opposite_length >= 1:
				# From opposite handle (or previous node)
				ux = (node.x - opposite.x) / opposite_length
				uy = (node.y - opposite.y) / opposite_length
			elif node_partner_length >= 1:
				# From partner
				ux = (partner.x - node.x) / node_partner_length
				uy = (partner.y - node.y) / node_partner_length
			elif segment_length >= 1:
				# From segment
				ux = (next.x - node.x) / segment_length
				uy = (next.y - node.y) / segment_length
			else:
				# Can't find vector
				return
			# Check if handles are rotated or have a kink
			handles_rotated = handle_turned_backward and not handle_turned_to_opposite
			kink_backward = handle_length < 1 and not opposite_isnot_on_segment
			# If so, reverse vector
			if handles_rotated and (opposite is None or opposite_turned_backward):
				ux = -ux
				uy = -uy
			elif kink_backward and (opposite is None or opposite_turned_backward):
				ux = -ux
				uy = -uy
			# Place target length on vector
			target_x = node.x + (ux * target_length)
			target_y = node.y + (uy * target_length)
		# --------------------------------------------------
		# Align handle with partner handle
		else:
			if node_partner_length >= 2 and partner_is_within_segment:
				# Target is halfway to partner handle
				target_x = node.x + ((partner.x - node.x) / 2)
				target_y = node.y + ((partner.y - node.y) / 2)
			elif 2 > node_partner_length >= 1 and partner_is_within_segment:
				# Target is partner
				target_x = partner.x
				target_y = partner.y
			else:
				# Target is 1/3 to next node
				if segment_length >= 3:
					target_x = node.x + ((next.x - node.x) / 3)
					target_y = node.y + ((next.y - node.y) / 3)
				# Target is halfway to next node
				elif segment_length >= 2:
					target_x = node.x + ((next.x - node.x) / 2)
					target_y = node.y + ((next.y - node.y) / 2)
				# Target is next node
				else:
					target_x = next.x
					target_y = next.y
		# --------------------------------------------------
		# Move handle
		handle.x, handle.y = target_x, target_y
	# --------------------------------------------------
	# Check all on-curve nodes and its handles from both sides
	path_length = len(path.nodes)
	for i in range(path_length):
		node = path.nodes[i]
		# Start from on-curve node
		if node.type != OFFCURVE:
			# Check the previous handle
			if i-3 >= 0 and path.nodes[i-1].type == OFFCURVE:
				prev = None
				opposite = None
				if i+1 < path_length:
					opposite = path.nodes[i+1]
					if opposite.type == OFFCURVE:
						if i+3 < path_length and path.nodes[i+3].type != OFFCURVE:
							prev = path.nodes[i+3]
				handle = path.nodes[i-1]
				partner = path.nodes[i-2]
				next = path.nodes[i-3]
				check_handle(path, prev, opposite, node, handle, partner, next)
			# Check the next handle
			if i+3 < path_length and path.nodes[i+1].type == OFFCURVE:
				prev = None
				opposite = None
				if i-1 >= 0:
					opposite = path.nodes[i-1]
					if opposite.type == OFFCURVE:
						if i-3 >= 0 and path.nodes[i-3].type != OFFCURVE:
							prev = path.nodes[i-3]
				handle = path.nodes[i+1]
				partner = path.nodes[i+2]
				next = path.nodes[i+3]
				check_handle(path, prev, opposite, node, handle, partner, next)



# Shorten handles that have a loop (double intersection) or inflection (single intersection)
# Shorten handles on curve segment
def shorten_inflected_handles_on_segment(n1, h1, h2, n2):
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
			dist1 = max(0, h1_len - INFLECTION_BUFFER)
			dist2 = max(0, h2_len - INFLECTION_BUFFER)
		else:
			# Check vectors and distances
			v1_to_inter = (interpoint[0] - n1.x, interpoint[1] - n1.y)
			v2_to_inter = (interpoint[0] - n2.x, interpoint[1] - n2.y)
			v1_dir = (h1.x - n1.x, h1.y - n1.y)
			v2_dir = (h2.x - n2.x, h2.y - n2.y)
			# Check if intersection is on front side (between nodes)
			dist1 = max(0, math.hypot(v1_to_inter[0], v1_to_inter[1]) - INFLECTION_BUFFER)
			dist2 = max(0, math.hypot(v2_to_inter[0], v2_to_inter[1]) - INFLECTION_BUFFER)
			dot1 = v1_to_inter[0]*v1_dir[0] + v1_to_inter[1]*v1_dir[1]
			dot2 = v2_to_inter[0]*v2_dir[0] + v2_to_inter[1]*v2_dir[1]
			# Check if at least one handle overshot the vector of other handle
			# Skip the case when handle tip lies on vector of other handle but not overshot it
			if (dot1 > 0 and dot2 > 0) and ((dist1 + INFLECTION_BUFFER) < h1_len or (dist2 + INFLECTION_BUFFER) < h2_len):
				# One or both handles have intersection on the front side
				intersection = True
	if intersection:
		# Calculate minimal handle length dynamically depending of segment length
		# Like 1/5 of segment length but not shorter than a constant
		# This helps to avoid kinks after shortening
		min_length = max(seg_len / 5, INFLECTION_HANDLE_MIN_LENGTH)
		# Shorten handles that go beyond intersection point
		def shorten_handle(node, handle, length, min_length, distance):
			if length != 0:
				new_length = max(distance, min_length)
				target_x = node.x + (((handle.x - node.x) / length) * new_length)
				target_y = node.y + (((handle.y - node.y) / length) * new_length)
				handle.x, handle.y = target_x, target_y
		# Check first handle
		if dist1 < h1_len > min_length:
			shorten_handle(n1, h1, h1_len, min_length, dist1)
		# Check second handle
		if dist2 < h2_len > min_length:
			shorten_handle(n2, h2, h2_len, min_length, dist2)
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
		if angle_deg > INFLECTION_S_MIN_ANGLE:
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
				h1_new_len -= INFLECTION_BUFFER
				h2_new_len -= INFLECTION_BUFFER
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
# --------------------------------------------------
# Shorten handles on path, segment by segment
def shorten_inflected_handles(path):
	path_length = len(path.nodes)
	if path_length < 4:
		return
	for i in range(path_length):
		if i < 3:
			continue
		if path.nodes[i].type != CURVE:
			continue
		# Check each curve segment
		n1 = path.nodes[i-3]
		h1 = path.nodes[i-2]
		h2 = path.nodes[i-1]
		n2 = path.nodes[i]
		shorten_inflected_handles_on_segment(n1, h1, h2, n2)



# Simplify Path
def simplify_path(path):
	# Smooth out ripples on almost straight sequences
	smooth_out_ripples(path)
	# Fix zero/turned-backward/rotated handles by pulling them out from node to inner side of segment
	# First pass is required to preserve the shape when removing nodes
	fix_degraded_handles(path)
	# Remove nodes that lies too close in range of distance and angle thresholds except smooth extremes
	remove_tight_nodes(path)
	# Fix zero/turned-backward/rotated handles again
	# Second pass is required to fix possible zero handles produced by removed nodes
	fix_degraded_handles(path)
	# Shorten handles that have a loop or inflection
	shorten_inflected_handles(path)



# Run as a standalone script only if not imported from a plugin
if __name__ == "__main__":
	Glyphs.font.disableUpdateInterface()
	try:
		# Process selected path or all paths on selected layer
		layer = Glyphs.font.selectedLayers[0]
		if layer.selection:
			paths = {node.parent for node in layer.selection if isinstance(node, GSNode)}
		else:
			paths = layer.paths
		for path in paths:
			simplify_path(path)
	except Exception as e:
		print("Error in Simplify Path:", e)
	finally:
		Glyphs.font.enableUpdateInterface()
		Glyphs.redraw()
