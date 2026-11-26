-- cloud-sessions for Rex: toggles the cloud sessions list in a split right of the focused pane.
-- Load it from ~/.config/rex/init.lua:
--   dofile(os.getenv("HOME") .. "/Development/skills/mods/cloud-sessions/rex/cloud_sessions.lua")

local LABEL = "cloud-sessions"
-- Resolved in the pane, on the host of the session it opens in: a Mac's key can open
-- the list in a remote host's session, where the Mac's home and shell don't exist.
local SCRIPT = '"$HOME/Development/skills/mods/cloud-sessions/rex/cloud_sessions.py"'

local function quote(s)
  return "'" .. s:gsub("'", "'\\''") .. "'"
end

rex.action{
  name = "cloud_sessions",
  title = "Toggle Cloud Sessions",
  description = "Show or hide the cloud sessions list beside the focused pane.",
  keywords = "claude cloud sessions remote status",
  run = function(ctx, args)
    local view, err = rex.session.view{}
    if view == nil then error(err, 0) end
    for _, w in ipairs(view.windows) do
      local here, list = false, nil
      for _, layer in ipairs(w.layers) do
        for _, b in ipairs(layer.blocks) do
          if b.block_id == ctx.block_id then here = true end
          if b.label == LABEL then list = b.block_id end
        end
      end
      if here then
        if list ~= nil then
          local _, cerr = rex.call("block.close", { session_id = ctx.session_id, block_id = list })
          if cerr ~= nil then error(cerr, 0) end
          return { closed = list }
        end
        local list_cmd = "exec python3 " .. SCRIPT
        local cmd = 'exec "${SHELL:-/bin/sh}" -lc ' .. quote(list_cmd)
        local r, serr = rex.session.new_split{
          anchor_id = ctx.block_id,
          direction = "horizontal",
          side = "after",
          ratio = 0.68,
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
    error("no focused pane to put the cloud sessions list beside", 0)
  end,
}

rex.bind("alt+cmd+c", "cloud_sessions")
