import pycozmo
from pycozmo import Client, LiftPosition
from pycozmo.util import Pose, Vector3, Angle, Distance, Speed #, Rotation
import time
import threading
import math

from pycozmo.expressions import Amazement, Excitement, Happiness, Sadness, Anger, Boredom, Surprise
import quaternion
import io
import json

animations = {
	"GREETING": "anim_greeting_happy_01",
	"SNEEZE": "anim_petdetection_shortreaction_01",
	"WHAT": "anim_vc_reaction_whatwasthat_01",
	"WIN": "anim_majorwin",
	"LOSE": "anim_majorfail",
	"FACEPALM": "anim_hiccup_faceplant_01",
	"BEEPING": "anim_explorer_drvback_loop_01",
	"NEW_OBJECT": "anim_launch_cubediscovery",
	"LOST_SOMETHING": "anim_energy_cubenotfound_01",
	"REJECT": "anim_cozmosays_badword_01",
	"FAILED": "anim_majorfail",
	"EXCITED_GREETING": "anim_meetcozmo_celebration",
	"TALKY_GREETING": "anim_greeting_happy_01"
}

emotions = {
	"AMAZED": Amazement,
	"PLEASED": Happiness,
	"HAPPY": Excitement,
	"UPSET": Sadness,
	"ANGRY": Anger,
	"BORED": Boredom,
	"STARTLED": Surprise
}

class Cube:
	def __init__(self, object_id):
		self.object_id = object_id
		self.is_visible = False
		self.pose = Pose(0, 0, 0, angle_z=Angle(radians=0))

class CozmoWorld:
	def __init__(self, cli):
		self.light_cubes = {
			1: Cube('1?'),
			2: Cube('2?'),
			3: Cube('3?')
		}
		available_objects = dict(cli.available_objects)
		found_cubes = 0
		for factory_id, obj in available_objects.items():
			dir(obj)
			if obj.object_type == pycozmo.protocol_encoder.ObjectType.Block_LIGHTCUBE1:
				self.light_cubes[1] = Cube(obj.factory_id)
				found_cubes += 1
			elif obj.object_type == pycozmo.protocol_encoder.ObjectType.Block_LIGHTCUBE2:
				self.light_cubes[2] = Cube(obj.factory_id)
				found_cubes += 1
			elif obj.object_type == pycozmo.protocol_encoder.ObjectType.Block_LIGHTCUBE3:
				self.light_cubes[3] = Cube(obj.factory_id)
				found_cubes += 1
			else:
				continue

			dir(obj)
			if found_cubes >= 3:
				break


def custom_dir(c, add): return dir(type(c)) + list(c.__dict__.keys()) + add


class GetAttr:
	"""Base class for attr accesses in `self._xtra` passed down to `self.default`"""
	@property
	def _xtra(self): return [o for o in dir(self.default) if not o.startswith('_')]

	def __getattr__(self, k):
		if k in self._xtra: return getattr(self.default, k)
		raise AttributeError(k)

	def __dir__(self): return custom_dir(self, self._xtra)


class RobotWithWorld(GetAttr):
	def __init__(self, cli):
		self.default = cli
		self.world = CozmoWorld(cli)
	#
	# def __getattr__(self, name):
	# 	return getattr(self.cli, name)
		# raise AttributeError

	# @property
	# def pose(self):
	# 	return self.default.pose

	# def set_head_angle(self, angle: float, accel: float = 10.0, max_speed: float = 10.0, duration: float = 0.0):
	# 	self.default.set_head_angle(angle, float, accel, max_speed, duration)

	# def wrapper(*args, **kwargs):
	# 	for delegate_object_str, delegated_methods in delegation_config.items():
	# 	if called_method in delegated_methods:
	# 		break
	# else:
	# 	__raise_standard_error()
	#
	# delegate_object = getattr(self, delegate_object_str, None)
	#
	# return getattr(delegate_object, called_method)(*args, **kwargs)
# return wrapper

class CozmoBot:
	def __init__(self, aruco):
		self._robot = None
		self._origin = None
		self._dataPubThread = None
		self._camClient = None
		self._wsClient = None
		self._latest_image = None
		self._aruco = aruco

	def start(self, code):
		from ws4py.client.threadedclient import WebSocketClient
		self._camClient = WebSocketClient('ws://localhost:9090/camPub')
		self._camClient.connect()

		self._wsClient = WebSocketClient('ws://localhost:9090/WsPub')
		self._wsClient.connect()

		self._dataPubThread = threading.Thread(target=self.feedRobotDataInThread)
		self._dataPubThread.daemon = True
		self._dataPubThread.start()

		# pycozmo.robot.Robot.drive_off_charger_on_connect = False
		with pycozmo.connect(enable_procedural_face=False) as cli:
			print('connected:')
			# self._robot = cli
			self._robot = RobotWithWorld(cli)
			self._origin = self._robot.pose

			# self.cubes_to_numbers = {}
			# for key in self._robot.world.light_cubes:
			# 	self.cubes_to_numbers[self._robot.world.light_cubes.get(key).object_id] = key
			# self.resetCubes()
			# self.resetCustomObjects()

			self._latest_image = None
			# print(self)
			cli.add_handler(pycozmo.event.EvtNewRawCameraImage, self.on_camera_image)
			cli.enable_camera(enable=True, color=True)
			cli.load_anims()

			bot = self
			# import pycozmo
			# print('running code:', code)
			exec(code, locals(), locals())

	def on_camera_image(self, cli, image):
		# print('self.on_image', image)
		self._latest_image = image

	def feedRobotDataInThread(self):
		print('Starting data feed')
		while True:
			if self._robot is None:
				# print('No robot')
				time.sleep(0.1)
				continue
			# Feed camera
			image = self._latest_image
			if image is None:
				# print('No image')
				time.sleep(0.1)
				continue
			fobj = io.BytesIO()
			image.save(fobj, format="jpeg")
			fobj.seek(0)
			binaryImage = fobj.read()
			if binaryImage is None:
				continue
			# print("sending image")
			self._camClient.send(binaryImage, binary=True)

			# Feed robot data
			def getData(pose):
				# Don't fail if one of the cubes has flat battery.
				if not pose:
					return {
						'x': 0,
						'y': 0,
						'z': 0,
						'rot': (0, 0, 0, 0)
					}
				pos = pose.position - self._origin.position
				rot = quaternion.div(pose.rotation.q0_q1_q2_q3, self._origin.rotation.q0_q1_q2_q3)
				return {
					'x': pos.x,
					'y': pos.y,
					'z': pos.z,
					'rot': rot
				}

			def getCubeData(num):
				cube = self._robot.world.light_cubes.get(num)
				data = getData(cube.pose)
				data['seen'] = self.getCubeSeen(num)
				data['visible'] = self.getCubeIsVisible(num)
				return data

			data = {
				'cozmo': getData(self._robot.pose),
				'cubes': [
					getCubeData(1),
					getCubeData(2),
					getCubeData(3)
				]
			}
			self._wsClient.send(json.dumps(data))
			# Sleep a while
			time.sleep(0.1)

	def resetCubes(self):
		'''
		Resets position of all cubes to make them "not yet seen".
		'''
		for key in self._robot.world.light_cubes:
			cube = self._robot.world.light_cubes.get(key)
			# Don't fail if one of the cubes has flat battery.
			if cube.pose:
				cube.pose._position = Vector3(0, 0, 0)

	def resetCustomObjects(self):
		# self._robot.world.delete_all_custom_objects()
		return True

	def playAnimation(self, animation):
		self._robot.play_anim(animations[animation])
		self._robot.wait_for(pycozmo.event.EvtAnimationCompleted)

	def playEmotion(self, emotion):
		f = emotions[emotion]()
		f.render()

	def lift(self, height):
		'''
		height - float, 0=bottom to 1=top
		'''
		self._robot.set_lift_height(LiftPosition(ratio=height).height.mm)

	def head(self, angle):
		'''
		angle - degrees (low=-25, high=44.5)
		'''
		self._robot.set_head_angle(Angle(degrees=angle).radians)

	def getCubeNumber(self, cube):
		return self.cubes_to_numbers.get(cube.object_id)

	def getCubeSeen(self, cube_num):
		'''
		Returns whether cube has been seen since program start.
		'''
		cube = self._robot.world.light_cubes[cube_num]
		if cube.pose:
			pos = cube.pose.position.x_y_z
			return not (pos == (0.0, 0.0, 0.0))
		else:
			return False

	def getCubeIsVisible(self, cube_num):
		'''
		Returns whether cube is visible (in the view).
		'''
		cube = self._robot.world.light_cubes[cube_num]
		if cube:
			return cube.is_visible
		else:
			return False

	def getDistanceToCube(self, cube_num):
		'''
		Returns the distance to the cube if it has been seen since the program start, or 100000 otherwise.
		'''
		if not self.getCubeSeen(cube_num):
			return 100000
		cube = self._robot.world.light_cubes[cube_num]
		pos = self._robot.pose.position - cube.pose.position
		dist = math.sqrt(pos.x * pos.x + pos.y * pos.y + pos.z * pos.z) / 10.0
		return dist

	def getDistanceBetweenCubes(self, cube1_num, cube2_num):
		'''
		Returns the distance between two cubes if both have been seen since the program start, or 100000 otherwise.
		'''
		if not self.getCubeSeen(cube1_num) or not self.getCubeSeen(cube2_num):
			return 100000
		cube1 = self._robot.world.light_cubes[cube1_num]
		cube2 = self._robot.world.light_cubes[cube2_num]
		pos = cube1.pose.position - cube2.pose.position
		dist = math.sqrt(pos.x * pos.x + pos.y * pos.y + pos.z * pos.z) / 10.0
		return dist

	def pickupCube(self, cube_num):
		'''
		Now this is tricky because the action is quite unreliable.
		'''
		# Ignore if cube has not been observed yet.
		if not self.getCubeSeen(cube_num):
			print("[Bot] Ignoring pickupCube() as the cube has not been observed yet")
			return False
		return False

	# cube = self._robot.world.light_cubes[cube_num]
	# # res = self._robot.pickup_object(cube).wait_for_completed()
	# # print('pickupCube res:', res)
	# res = None
	# while res == None or (res.state == cozmo.action.ACTION_FAILED and res.failure_reason[1] in ["repeat", "aborted"]):
	# # while res == None or res.state == cozmo.action.ACTION_FAILED:
	# 	res = self._robot.pickup_object(cube).wait_for_completed()
	# 	print('pickupCube res:', res)
	# return res.state == cozmo.action.ACTION_SUCCEEDED

	def placeCubeOnGround(self, cube_num):
		if not self.getCubeSeen(cube_num):
			print("[Bot] Ignoring placeCubeOnGround() as the cube has not been observed yet")
			return False
		return False

	# cube = self._robot.world.light_cubes[cube_num]
	# res = self._robot.place_object_on_ground_here(cube).wait_for_completed()
	# return res.state == cozmo.action.ACTION_SUCCEEDED

	def placeCubeOnCube(self, other_cube_num):
		'''
		Another unreliable action.
		'''
		if not self.getCubeSeen(other_cube_num):
			print("[Bot] Ignoring placeCubeOnCube() as the cube has not been observed yet")
			return False
		return False

	# print("[Bot] Executing placeCubeOnCube()")
	# cube = self._robot.world.light_cubes[other_cube_num]
	# # while res == None or (res.state == cozmo.action.ACTION_FAILED and res.failure_code in ["repeat", "aborted"]):
	# # 	res = self._robot.go_to_object(cube, distance_mm(100)).wait_for_completed()
	# # 	print(res)
	# # if res.state == cozmo.action.ACTION_SUCCEEDED:
	# # 	res = None
	# res = None
	# while res == None or (res.state == cozmo.action.ACTION_FAILED and res.failure_code in ["repeat", "aborted"]):
	# 	res = self._robot.place_on_object(cube).wait_for_completed()
	# 	print(res)
	# print("[Bot] placeCubeOnCube() finished")
	# return res.state == cozmo.action.ACTION_SUCCEEDED

	def gotoOrigin(self):
		res = self._robot.go_to_pose(self._origin)
		return True

	def say(self, text):
		print("[Bot] Executing Say: " + text)
		# res = self._robot.say_text(text).wait_for_completed()
		# print("[Bot] Say finished")
		# return res.state == cozmo.action.ACTION_SUCCEEDED
		return False

	def enableFreeWill(self, enable):
		print("[Bot] Executing enableFreeWill(" + str(enable) + ")")
		if enable:
			self._robot.start_freeplay_behaviors()
		else:
			self._robot.stop_freeplay_behaviors()

	def stop(self):
		print("[Bot] Executing stop")
		self._robot.stop_all_motors()

	def delay(self, seconds):
		'''
		seconds - can be float for fractions of a second
		'''
		# print("[Bot] Executing delay " + str(seconds))
		time.sleep(seconds)

	def turn(self, angle):
		print("[Bot] Executing turn " + str(angle))
		res = self._robot.turn_in_place(Angle.degrees(angle)).wait_for_completed()
		print("[Bot] turn finished")
		return res.state == cozmo.action.ACTION_SUCCEEDED

	def turnTowardCube(self, cube_num):
		if not self.getCubeSeen(cube_num):
			print("[Bot] Ignoring turnTowardCube() as the cube has not been observed yet")
			return False
		print("[Bot] Executing turn toward cube")
		cube = self._robot.world.light_cubes[cube_num]
		pos = self._robot.pose.position - cube.pose.position
		angle = Angle.radians(math.atan2(pos.y, pos.x) - math.pi) - self._robot.pose.rotation.angle_z
		res = self._robot.turn_in_place(angle).wait_for_completed()
		print("[Bot] turn finished")
		return res.state == cozmo.action.ACTION_SUCCEEDED

	def driveDistanceWithSpeed(self, distance, speed):
		print("[Bot] Executing driveDistanceSpeed(" + str(distance) + ", " + str(speed) + ")")
		res = self._robot.drive_straight(Distance.mm(distance * 10), Speed.mmps(speed * 10))
		print("[Bot] driveDistanceSpeed finished")
		return True

	def driveWheelsWithSpeed(self, lSpeed, rSpeed):
		print("[Bot] Executing driveWheelsWithSpeed(" + str(lSpeed) + ", " + str(rSpeed) + ")")
		self._robot.drive_wheels(lSpeed * 10, rSpeed * 10)

	def driveTo(self, x, y):
		print("[Bot] Executing driveTo(" + str(x) + ", " + str(y) + ")")
		pose = Pose(x * 10, y * 10, 0, angle_z=self._robot.pose.rotation.angle_z)
		res = self._robot.go_to_pose(self._origin.define_pose_relative_this(pose))
		print("[Bot] driveTo finished")
		return True

	def waitForTap(self):
		print("[Bot] Executing waitForTap()")
		return self._robot.wait_for('ObjectTapped', timeout=None).obj

	def addStaticObject(self, model, x1, y1, x2, y2, depth, height):
		print("[Bot] Executing addStaticObject({},{},{},{},{},{})".format(x1, y1, x2, y2, depth, height))

		data = {
			'addStaticObject': {
				'model': model,
				'x1': x1,
				'y1': y1,
				'x2': x2,
				'y2': y2,
				'depth': depth,
				'height': height
			}
		}
		self._wsClient.send(json.dumps(data))

		X1 = x1 * 10
		Y1 = y1 * 10
		X2 = x2 * 10
		Y2 = y2 * 10
		HEIGHT = height * 10

		DEPTH = depth * 10
		WIDTH = math.sqrt(math.pow(X1 - X2, 2) + math.pow(Y1 - Y2, 2))
		centerX = (X1 + X2) / 2.0
		centerY = (Y1 + Y2) / 2.0
		centerZ = HEIGHT / 2.0
		angle = math.atan2(Y1 - Y2, X1 - X2)
		pose = Pose(centerX, centerY, centerZ, angle_z=Angle.radians(angle))
		self._robot.world.create_custom_fixed_object(self._origin.define_pose_relative_this(pose), WIDTH, DEPTH, HEIGHT)

	def setCubeModel(self, model, num):
		data = {
			'setCubeModel': {
				'model': model,
				'cubeNum': num
			}
		}
		self._wsClient.send(json.dumps(data))

	def highlight(self, block):
		data = {
			'highlight': block
		}
		self._wsClient.send(json.dumps(data))
