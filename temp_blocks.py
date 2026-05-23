from secontrol import Grid
grid = Grid.from_name("skynet-baza0")
blocks = grid.blocks

found = False
for blk_id, b in blocks.items():
    if b.name and "drill" in b.name.lower():
        print("Found drill block:")
        print("  name:", b.name)
        print("  local_position:", b.local_position)
        print("  block_id:", b.block_id)
        found = True
        break

if not found:
    print("No drill block found. First 5 blocks:")
    for blk_id, b in list(blocks.items())[:5]:
        print(f"  block_id={b.block_id}, name={b.name}, local_pos={b.local_position}")