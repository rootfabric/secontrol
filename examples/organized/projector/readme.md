
# выставить на малом проекторе, дочерняя сетка на роторе
C:\Python311\python.exe C:\secontrol\examples\organized\projector\align_clone_projection_small.py skynet-farpost0 "C:\Users\root\AppData\Roaming\SpaceEngineers\Blueprints\local\skynet-scout0" --normal=auto --projector-subtype=SmallProjector --no-live-blueprint-frame --runtime-transform-mode apply --strict-contact-verify

# установка большого грида
& C:\Python311\python.exe C:\secontrol\examples\organized\projector\align_clone_projection_large.py skynet-farpost0 "C:\Users\root\AppData\Roaming\SpaceEngineers\Blueprints\local\skynet-agent0" --normal=auto --strict-contact-verify

