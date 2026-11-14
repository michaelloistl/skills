-- drive-spec-view for Rex: toggles the drive-spec run view in a split right of the focused pane.
-- Load it from ~/.config/rex/init.lua:
--   dofile(os.getenv("HOME") .. "/Development/skills/mods/drive-spec-view/rex/drive_spec_view.lua")

local LABEL = "drive-spec-view"
-- Resolved in the pane, on the host of the session it opens in: a Mac's key can open
-- the view in a devbox session, where the Mac's home and shell don't exist.
local SCRIPT = '"$HOME/Development/skills/mods/drive-spec-view/rex/drive_spec_view.py"'

local function quote(s)
  return "'" .. s:gsub("'", "'\\''") .. "'"
end

rex.action{
  name = "drive_spec_view",
  title = "Toggle drive-spec Run",
  description = "Show or hide the drive-spec run the focused pane drives: steps, slices and agents.",
  keywords = "drive-spec spec run slices agents",
  run = function(ctx, args)
    local view, err = rex.session.view{}
    if view == nil then error(err, 0) end
    for _, w in ipairs(view.windows) do
      local here, view_block = false, nil
      for _, layer in ipairs(w.layers) do
        for _, b in ipairs(layer.blocks) do
          if b.block_id == ctx.block_id then here = true end
          if b.label == LABEL then view_block = b.block_id end
        end
      end
      if here then
        if view_block ~= nil then
          local _, cerr = rex.call("block.close", { session_id = ctx.session_id, block_id = view_block })
          if cerr ~= nil then error(cerr, 0) end
          return { closed = view_block }
        end
        local view_cmd = "exec python3 " .. SCRIPT .. " --block " .. quote(ctx.block_id)
        local cmd = 'exec "${SHELL:-/bin/sh}" -lc ' .. quote(view_cmd)
        local r, serr = rex.session.new_split{
          anchor_id = ctx.block_id,
          direction = "horizontal",
          side = "after",
          ratio = 0.62,
          layout = { block = {
            flavor = "com.superlogical.terminal.shell",
            label = LABEL,
            options = { command = { "/bin/sh", "-c", cmd }, shell = "none" },
          } },
        }
        if r == nil then error(serr, 0) end
        return r
      end
    end
    error("no focused pane to put the drive-spec view beside", 0)
  end,
}

rex.bind("alt+cmd+r", "drive_spec_view")
