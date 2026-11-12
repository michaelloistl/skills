-- pr-board for Rex: toggles the open PRs board in a split right of the focused pane.
-- Load it from ~/.config/rex/init.lua:
--   dofile(os.getenv("HOME") .. "/Development/skills/mods/pr-board/rex/pr_board.lua")

local LABEL = "pr-board"
-- Resolved in the pane, on the host of the session it opens in: a Mac's key can open
-- the board in a devbox session, where the Mac's home and shell don't exist.
local SCRIPT = '"$HOME/Development/skills/mods/pr-board/rex/pr_board.py"'

local function quote(s)
  return "'" .. s:gsub("'", "'\\''") .. "'"
end

rex.action{
  name = "pr_board",
  title = "Toggle Open PRs",
  description = "Show or hide the open PRs board beside the focused pane.",
  keywords = "prs pull requests github board",
  run = function(ctx, args)
    local view, err = rex.session.view{}
    if view == nil then error(err, 0) end
    for _, w in ipairs(view.windows) do
      local here, board = false, nil
      for _, layer in ipairs(w.layers) do
        for _, b in ipairs(layer.blocks) do
          if b.block_id == ctx.block_id then here = true end
          if b.label == LABEL then board = b.block_id end
        end
      end
      if here then
        if board ~= nil then
          local _, cerr = rex.call("block.close", { session_id = ctx.session_id, block_id = board })
          if cerr ~= nil then error(cerr, 0) end
          return { closed = board }
        end
        local board_cmd = "exec python3 " .. SCRIPT .. " --block " .. quote(ctx.block_id)
        local cmd = 'exec "${SHELL:-/bin/sh}" -lc ' .. quote(board_cmd)
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
    error("no focused pane to put the PR board beside", 0)
  end,
}

rex.bind("alt+cmd+p", "pr_board")
