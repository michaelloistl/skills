-- sysmon for Rex: toggles the System pane in a split right of the focused pane.
-- Load it from ~/.config/rex/init.lua:
--   dofile(os.getenv("HOME") .. "/Development/skills/mods/sysmon/rex/sysmon.lua")

local LABEL = "sysmon"
-- Resolved in the pane, on the host of the session it opens in: a Mac's key can open
-- the pane in a devbox session, where the Mac's home and shell don't exist.
local CMD = 'exec "${SHELL:-/bin/sh}" -lc \'exec python3 "$HOME/Development/skills/mods/sysmon/rex/sysmon.py"\''

rex.action{
  name = "sysmon",
  title = "Toggle System Monitor",
  description = "Show or hide CPU, memory, disk and process load beside the focused pane.",
  keywords = "sysmon system cpu memory load monitor",
  run = function(ctx, args)
    local view, err = rex.session.view{}
    if view == nil then error(err, 0) end
    for _, w in ipairs(view.windows) do
      local here, pane = false, nil
      for _, layer in ipairs(w.layers) do
        for _, b in ipairs(layer.blocks) do
          if b.block_id == ctx.block_id then here = true end
          if b.label == LABEL then pane = b.block_id end
        end
      end
      if here then
        if pane ~= nil then
          local _, cerr = rex.call("block.close", { session_id = ctx.session_id, block_id = pane })
          if cerr ~= nil then error(cerr, 0) end
          return { closed = pane }
        end
        local r, serr = rex.session.new_split{
          anchor_id = ctx.block_id,
          direction = "horizontal",
          side = "after",
          ratio = 0.68,
          layout = { block = {
            flavor = "com.superlogical.terminal.shell",
            label = LABEL,
            options = { command = { "/bin/sh", "-c", CMD }, shell = "none" },
          } },
        }
        if r == nil then error(serr, 0) end
        return r
      end
    end
    error("no focused pane to put the system monitor beside", 0)
  end,
}

rex.bind("shift+cmd+m", "sysmon")
