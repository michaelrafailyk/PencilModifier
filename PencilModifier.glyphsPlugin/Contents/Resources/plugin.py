# encoding: utf-8
# Pencil Modifier plugin for Glyphs
# Copyright: Michael Rafailyk, 2025, www.michaelrafailyk.com Version 1.0
# GitHub: https://github.com/michaelrafailyk/PencilModifier

import objc
from GlyphsApp.plugins import GeneralPlugin
from GlyphsApp import (
	Glyphs, PATH_MENU, DRAWFOREGROUND,
	MOUSEMOVED, MOUSEDRAGGED, MOUSEDOWN, MOUSEUP,
	OFFCURVE, CURVE, QCURVE, LINE
)
from AppKit import (
	NSMenu, NSMenuItem, NSOnState, NSOffState,
	NSEvent, NSEventMaskFlagsChanged, NSEventModifierFlagOption, NSEventModifierFlagShift,
	NSAttributedString, NSFont, NSFontAttributeName, NSForegroundColorAttributeName,
	NSBezierPath, NSPoint, NSColor,
)
from Foundation import NSTimer
import time

from SimplifyPath import simplify_path
from RedrawPath import identify_closest_area, redraw_path

__doc__ = """
Simplify Path — drawing with the Pencil tool produces a smooth path by removing tight nodes, smoothing ripples, and fixing degraded or inflected handles.
Redraw Path — hold Option ⌥ while drawing with the Pencil tool to merge drawn path with the nearest existing path, creating smooth connections where they join.
Draw Closed Path — hold Shift ⇧ while drawing with the Pencil tool to automatically close drawn path.
"""

class PencilModifier(GeneralPlugin):
	
	@objc.python_method
	def settings(self):
		self.name = "PencilModifier"
		self.menuName = "Pencil Modifier"
		self.DEFAULTS = f"com.michaelrafailyk.{self.name}"
		# Settings menu states
		self.SETTINGS = {
			"Enabled": True,
			"SimplifyPath": True,
			"ShadeTheArea": True,
			"AdjustConnections": True,
			"CorrectPathDirection": True,
		}
		# Current states
		self.PencilIsActive = False
		self.OptionIsLocked = False
		self.OptionIsHeld = False
		self.ShiftIsHeld = False
		self.undoManager = None
		self.getPathTimer = None
		self.getPathDelay = 0.025
		self.mousePosition = None
		self.mousePositionStart = None
		self.closestPath = None
		self.closestArea = None
		self.ShadeTheAreaTimestamp = 0
		self.ShadeTheAreaInterval = 0.05
	
	def start(self):
		# Build submenu
		def addMenuHeader(title):
			item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, None, "")
			item.setEnabled_(False)
			attributes = {
				NSFontAttributeName: NSFont.menuFontOfSize_(11),
				NSForegroundColorAttributeName: NSColor.disabledControlTextColor()
			}
			item.setAttributedTitle_(NSAttributedString.alloc().initWithString_attributes_(title, attributes))
			submenu.addItem_(item)
		def addMenuItem(title, action, settingsKey):
			item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, "")
			item.setTarget_(self)
			stateBool = Glyphs.defaults.get(
				f"{self.DEFAULTS}.{settingsKey}", self.SETTINGS[settingsKey]
			)
			item.setState_(NSOnState if stateBool else NSOffState)
			self.SETTINGS[settingsKey] = stateBool
			setattr(self, f"menu{settingsKey}", item)
			submenu.addItem_(item)
		def addMenuSeparator():
			submenu.addItem_(NSMenuItem.separatorItem())
		submenu = NSMenu.alloc().initWithTitle_(self.menuName)
		addMenuItem("Enable Plugin", "togglePlugin:", "Enabled")
		addMenuItem("Simplify Drawn Path", "updateSimplifyPath:", "SimplifyPath")
		addMenuSeparator()
		addMenuHeader("Redraw Path\t\t\t\tPencil ⌥")
		addMenuItem("Shade the Area", "updateShadeTheArea:", "ShadeTheArea")
		addMenuItem("Adjust Connections", "updateAdjustConnections:", "AdjustConnections")
		addMenuSeparator()
		addMenuHeader("Draw Closed Path\t\t\tPencil ⇧")
		addMenuItem("Correct Path Direction", "updateCorrectPathDirection:", "CorrectPathDirection")
		menuEntry = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(self.menuName, None, "")
		menuEntry.setSubmenu_(submenu)
		Glyphs.menu[PATH_MENU].append(menuEntry)
		# Activate/deactivate plugin at launch
		if self.SETTINGS["Enabled"]:
			self.activate()
		else:
			self.deactivate()
		# Update current state if Option is held
		def flagsChangedHandler_(event):
			state = (event.modifierFlags() & NSEventModifierFlagOption) == NSEventModifierFlagOption
			if self.PencilIsActive and not self.OptionIsLocked:
				self.OptionIsHeld = state
				if self.SETTINGS["ShadeTheArea"]:
					self.redrawEditView()
			return event
		if not hasattr(self, "_flagsChangedMonitor"):
			self._flagsChangedMonitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
				NSEventMaskFlagsChanged, flagsChangedHandler_
			)
	
	# Menu actions
	# Main toggler to enable/disable the plugin
	def togglePlugin_(self, sender):
		self.SETTINGS["Enabled"] = not self.SETTINGS.get("Enabled", False)
		if self.SETTINGS["Enabled"]:
			self.activate()
			self.menuEnabled.setState_(NSOnState)
		else:
			self.deactivate()
			self.menuEnabled.setState_(NSOffState)
		Glyphs.defaults[f"{self.DEFAULTS}.Enabled"] = self.SETTINGS["Enabled"]
	# When plugin is disabled, gray out submenu items except main toggler and headers/separators
	def validateMenuItem_(self, menuItem):
		if not menuItem.action():
			return False
		if not self.SETTINGS.get("Enabled", False):
			if menuItem != self.menuEnabled:
				return False
		return True
	# Toggle menu item and update SETTINGS and user defaults
	@objc.python_method
	def toggleMenuItemState(self, attrName, settingsKey):
		item = getattr(self, attrName)
		state = NSOffState if item.state() == NSOnState else NSOnState
		item.setState_(state)
		stateBool = (state == NSOnState)
		self.SETTINGS[settingsKey] = stateBool
		Glyphs.defaults[f"{self.DEFAULTS}.{settingsKey}"] = stateBool
	# Actions for plugin settings items
	def updateSimplifyPath_(self, sender):
		self.toggleMenuItemState("menuSimplifyPath", "SimplifyPath")
	def updateShadeTheArea_(self, sender):
		self.toggleMenuItemState("menuShadeTheArea", "ShadeTheArea")
	def updateAdjustConnections_(self, sender):
		self.toggleMenuItemState("menuAdjustConnections", "AdjustConnections")
	def updateCorrectPathDirection_(self, sender):
		self.toggleMenuItemState("menuCorrectPathDirection", "CorrectPathDirection")
	
	# Start watching when plugin is actived
	def activate(self):
		Glyphs.addCallback(self.handleMouseMoved, MOUSEMOVED)
		Glyphs.addCallback(self.handleMouseMoved, MOUSEDRAGGED)
		Glyphs.addCallback(self.handleMouseDown, MOUSEDOWN)
		Glyphs.addCallback(self.handleMouseUp, MOUSEUP)
		Glyphs.addCallback(self.drawForeground, DRAWFOREGROUND)
	# Stop watching when plugin is deactivated
	def deactivate(self):
		Glyphs.removeCallback(self.handleMouseMoved, MOUSEMOVED)
		Glyphs.removeCallback(self.handleMouseMoved, MOUSEDRAGGED)
		Glyphs.removeCallback(self.handleMouseDown, MOUSEDOWN)
		Glyphs.removeCallback(self.handleMouseUp, MOUSEUP)
		Glyphs.removeCallback(self.drawForeground, DRAWFOREGROUND)
		# Clear current states
		self.clearStates()
		if self.undoManager is not None:
			try:
				self.undoManager.endUndoGrouping()
			except Exception:
				pass
			self.undoManager = None
		if self.getPathTimer is not None:
			try:
				self.getPathTimer.invalidate()
			except Exception:
				pass
			self.getPathTimer = None
	
	# Clear current states
	def clearStates(self):
		self.PencilIsActive = False
		self.OptionIsLocked = False
		self.OptionIsHeld = False
		self.ShiftIsHeld = False
		self.mousePosition = None
		self.mousePositionStart = None
		self.closestPath = None
		self.closestArea = None
	
	# Mouse Moved event
	@objc.python_method
	def handleMouseMoved(self, notification):
		# Check if Pencil tool is active
		if Glyphs.font.tool not in ("PenTool", "GSToolGroup"):
			if self.PencilIsActive:
				# Clear current states
				self.clearStates()
				if self.SETTINGS["ShadeTheArea"]:
					self.redrawEditView()
			return
		self.PencilIsActive = True
		# Save mouse cursor position in Edit View
		if self.SETTINGS["ShadeTheArea"]:
			tab = Glyphs.font.currentTab
			view = tab.graphicView() if tab else None
			event = Glyphs.currentEvent() if view else None
			if event:
				self.mousePosition = view.getActiveLocation_(event)
				self.redrawEditView()
	
	# Mouse Down event
	@objc.python_method
	def handleMouseDown(self, notification):
		# Check if Pencil tool is active
		if Glyphs.font.tool not in ("PenTool", "GSToolGroup"):
			if self.PencilIsActive:
				# Clear current states
				self.clearStates()
				if self.SETTINGS["ShadeTheArea"]:
					self.redrawEditView()
			return
		self.PencilIsActive = True
		# Lock the Option key state
		self.OptionIsLocked = True
		# Check if Shift key is held down when start drawing
		event = notification.object()
		self.OptionIsHeld = bool(event.modifierFlags() & NSEventModifierFlagOption)
		self.ShiftIsHeld = bool(event.modifierFlags() & NSEventModifierFlagShift)
		# Save mouse cursor position in Edit View
		if self.SETTINGS["ShadeTheArea"]:
			tab = Glyphs.font.currentTab
			view = tab.graphicView() if tab else None
			event = Glyphs.currentEvent() if view else None
			if event:
				self.mousePosition = view.getActiveLocation_(event)
				self.mousePositionStart = self.mousePosition
				self.redrawEditView()
	
	# Mouse Up event
	@objc.python_method
	def handleMouseUp(self, notification):
		# Clear any possible hanged previous undo grouping and timer
		if self.undoManager is not None:
			try:
				self.undoManager.endUndoGrouping()
			except Exception:
				pass
			self.undoManager = None
		if self.getPathTimer is not None:
			try:
				self.getPathTimer.invalidate()
			except Exception:
				pass
			self.getPathTimer = None
		# Check if Pencil tool is active
		if Glyphs.font.tool not in ("PenTool", "GSToolGroup"):
			# Clear current states
			self.clearStates()
			if self.SETTINGS["ShadeTheArea"]:
				self.redrawEditView()
			return
		# Check if processing is required
		if not (self.SETTINGS["SimplifyPath"] or self.OptionIsHeld or self.ShiftIsHeld):
			return
		# Begin undo grouping
		layer = Glyphs.font.selectedLayers[0]
		self.undoManager = layer.undoManager()
		self.undoManager.beginUndoGrouping()
		# Get drawn path after delay
		userInfo = {"OptionIsHeld": self.OptionIsHeld, "ShiftIsHeld": self.ShiftIsHeld}
		self.getPathTimer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
			self.getPathDelay, self, "getPath:", userInfo, False
		)
		# Clear current states (except: PencilIsActive, mousePosition, ShadeTheAreaTimestamp)
		self.OptionIsLocked = False
		self.OptionIsHeld = False
		self.ShiftIsHeld = False
		self.mousePositionStart = None
		self.closestPath = None
		self.closestArea = None
		if self.SETTINGS["ShadeTheArea"]:
			self.redrawEditView()
	
	# Get drawn path and process it
	def getPath_(self, timer):
		# Receive modifier flags
		flags = timer.userInfo()
		OptionIsHeld = flags.get("OptionIsHeld", False)
		ShiftIsHeld = flags.get("ShiftIsHeld", False)
		# Clear timer
		timer.invalidate()
		self.getPathTimer = None
		# Process path
		Glyphs.font.disableUpdateInterface()
		try:
			# Get drawn path
			layer = Glyphs.font.selectedLayers[0]
			paths = [p for p in layer.paths if p.nodes]
			if len(paths) == 0:
				return
			path = paths[-1]
			# Simplify Path
			if self.SETTINGS["SimplifyPath"]:
				try:
					simplify_path(path)
				except Exception as e:
					print("Error in Simplify Path:", e)
			# Redraw Path
			if OptionIsHeld and len(paths) >= 2:
				try:
					redraw_path(layer, paths, path, self.SETTINGS["AdjustConnections"])
				except Exception as e:
					print("Error in Redraw Path:", e)
			# Close Drawn Path
			elif ShiftIsHeld:
				path.closed = True
				if self.SETTINGS["CorrectPathDirection"]:
					layer.correctPathDirection()
		except Exception as e:
			print(f"Error in {self.menuName}:", e)
		finally:
			Glyphs.font.enableUpdateInterface()
			Glyphs.redraw()
			# End undo grouping
			if self.undoManager:
				actionName = self.menuName
				if OptionIsHeld:
					actionName = "Redraw Path"
				elif ShiftIsHeld:
					actionName = "Draw Closed Path"
				elif self.SETTINGS["SimplifyPath"]:
					actionName = "Draw Simplified Path"
				try:
					self.undoManager.setActionName_(actionName)
					self.undoManager.endUndoGrouping()
				except Exception:
					pass
				self.undoManager = None
	
	
	
	# Force to redraw in Edit View tab
	def redrawEditView(self):
		font = Glyphs.font
		if font:
			tab = Glyphs.font.currentTab
			if tab:
				view = tab.graphicView()
				if view:
					view.setNeedsDisplay_(True)
	
	# Shade the closest area on foreground
	@objc.python_method
	def drawForeground(self, layer, darkAndScale):
		if not self.SETTINGS["ShadeTheArea"]:
			return
		if not self.PencilIsActive or not self.OptionIsHeld or self.mousePosition is None:
			return
		# --------------------------------------------------
		# Find closest area
		# Make request no more frequently than threshold interval (50 milliseconds by default)
		# Otherwise use previously saved closest area
		timestamp = time.time()
		if timestamp - self.ShadeTheAreaTimestamp > self.ShadeTheAreaInterval:
			self.ShadeTheAreaTimestamp = timestamp
			mousePosition = self.mousePosition
			if self.mousePositionStart is not None:
				mousePositionStart = self.mousePositionStart
			else:
				mousePositionStart = self.mousePosition
			layer = Glyphs.font.selectedLayers[0]
			paths = [p for p in layer.paths if p.nodes]
			try:
				(
					closest_path, closest_area, CS1, CE1, CS_vector, CE_vector, open_wraparound
				) = identify_closest_area(paths, None, mousePositionStart, mousePosition)
				# Update closest area with received data
				if closest_path is not None and closest_area is not None:
					self.closestPath = closest_path
					self.closestArea = closest_area
				# Nothing found, do not shade the closest area anything
				else:
					self.closestPath = None
					self.closestArea = None
			except Exception as e:
				print("Error in Shade the Area:", e)
				self.closestPath = None
				self.closestArea = None
		if self.closestArea is None:
			return
		# --------------------------------------------------
		# Draw Bezier path
		nodes = self.closestPath.nodes
		nodes_length = len(nodes)
		path_is_closed = self.closestPath.closed
		# Normalise reverse order no normal order
		if ((self.closestArea[0] - self.closestArea[1]) % nodes_length == 1):
			self.closestArea.reverse()
		# Collect on-curve nodes (use modulo only if path is closed)
		if path_is_closed:
			oncurve_nodes = [i for i in self.closestArea if nodes[i % nodes_length].type != OFFCURVE]
		else:
			oncurve_nodes = [i for i in self.closestArea if nodes[i].type != OFFCURVE]
		if not oncurve_nodes:
			return
		shade_path = NSBezierPath.bezierPath()
		# Move to first on-curve
		if path_is_closed:
			shade_path.moveToPoint_(nodes[oncurve_nodes[0] % nodes_length].position)
		else:
			shade_path.moveToPoint_(nodes[oncurve_nodes[0]].position)
		# Iterate through on-curve pairs
		for j in range(1, len(oncurve_nodes)):
			start_idx = oncurve_nodes[j-1]
			end_idx   = oncurve_nodes[j]
			# Get intermediate nodes
			if path_is_closed:
				intermediate = [nodes[k % nodes_length] for k in range(start_idx + 1, end_idx)]
				end_node = nodes[end_idx % nodes_length]
			else:
				intermediate = [nodes[k] for k in range(start_idx + 1, end_idx)]
				end_node = nodes[end_idx]
			end_pos  = end_node.position
			# Line segment
			if end_node.type == LINE:
				shade_path.lineToPoint_(end_pos)
			# Cubic segment
			elif end_node.type == CURVE:
				if len(intermediate) == 2:
					cp1 = intermediate[0].position
					cp2 = intermediate[1].position
					shade_path.curveToPoint_controlPoint1_controlPoint2_(end_pos, cp1, cp2)
				else:
					shade_path.lineToPoint_(end_pos)
			# Quadratic segment
			elif end_node.type == QCURVE:
				if len(intermediate) == 0:
					shade_path.lineToPoint_(end_pos)
				else:
					def quadratic_to_cubic(P0, Q, P2):
						C1 = NSPoint(P0.x + 2/3*(Q.x - P0.x), P0.y + 2/3*(Q.y - P0.y))
						C2 = NSPoint(P2.x + 2/3*(Q.x - P2.x), P2.y + 2/3*(Q.y - P2.y))
						return C1, C2
					prev = nodes[start_idx % nodes_length].position
					handles = [n.position for n in intermediate]
					for i, cp in enumerate(handles):
						is_last = (i == len(handles) - 1)
						if is_last:
							c1, c2 = quadratic_to_cubic(prev, cp, end_pos)
							shade_path.curveToPoint_controlPoint1_controlPoint2_(end_pos, c1, c2)
						else:
							next_cp = handles[i+1]
							mid = NSPoint((cp.x + next_cp.x)/2.0, (cp.y + next_cp.y)/2.0)
							c1, c2 = quadratic_to_cubic(prev, cp, mid)
							shade_path.curveToPoint_controlPoint1_controlPoint2_(mid, c1, c2)
							prev = mid
			# Broken segment with unknown type
			else:
				shade_path.lineToPoint_(end_pos)
		# --------------------------------------------------
		# Stroke settings
		strokeWidth = 3 / darkAndScale["Scale"]
		strokeColor = "#FFFFFF"
		if darkAndScale["Black"]:
			strokeColor = "#0d0d0d"
		strokeOpacity = 0.8
		# Set color and stroke
		NSColor.colorWithString_(strokeColor).colorWithAlphaComponent_(strokeOpacity).set()
		shade_path.setLineWidth_(strokeWidth)
		shade_path.stroke()
	
	
	
	@objc.python_method
	def __file__(self):
		return __file__
