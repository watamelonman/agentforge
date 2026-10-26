## Headless compile check: loads every script under res://src and res://test so parse errors and
## typing warnings-as-errors (project.godot [debug]) fail the gate even if no scene uses the script.
extends SceneTree

var _failed: int = 0


func _init() -> void:
	for dir: String in ["res://src", "res://test"]:
		_scan(dir)
	print("check_scripts: %d failure(s)" % _failed)
	quit(1 if _failed > 0 else 0)


func _scan(dir: String) -> void:
	for sub: String in DirAccess.get_directories_at(dir):
		_scan(dir.path_join(sub))
	for f: String in DirAccess.get_files_at(dir):
		if f.ends_with(".gd"):
			var s: Script = load(dir.path_join(f)) as Script
			if s == null or not s.can_instantiate():
				printerr("FAILED: ", dir.path_join(f))
				_failed += 1
