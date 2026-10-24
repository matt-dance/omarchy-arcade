.pragma library

function pluginId(manifest) {
  return (manifest && manifest.id) ? manifest.id : "matt-dance.arcade"
}

function sourceLabel(source) {
  var map = {
    steam: "Steam",
    heroic: "Heroic",
    legendary: "Legendary",
    lutris: "Lutris",
    bottles: "Bottles",
    itch: "itch.io",
    gfn: "GeForce NOW",
    desktop: "Desktop",
    webapp: "Cloud",
    retroarch: "RetroArch",
    roms: "ROMs",
    moonlight: "Moonlight"
  }
  return map[source] || source || ""
}

function runnerBadge(runner) {
  if (runner === "proton") return "Proton"
  if (runner === "cloud") return "Cloud"
  if (runner === "emulator") return "Emu"
  if (runner === "flatpak") return "Flatpak"
  if (runner === "stream") return "Stream"
  return ""
}

function filterGames(games, query) {
  var q = String(query || "").trim().toLowerCase()
  if (!q.length) return games.slice()
  var out = []
  for (var i = 0; i < games.length; i++) {
    var g = games[i]
    var hay = (g.title || "") + " " + (g.source || "") + " " + (g.store || "") + " " + (g.platform || "")
    if (hay.toLowerCase().indexOf(q) !== -1)
      out.push(g)
  }
  return out
}

function recentGames(games, limit) {
  var copy = games.slice()
  copy.sort(function(a, b) {
    var la = a.lastPlayed || ""
    var lb = b.lastPlayed || ""
    if (la === lb) return String(a.sortTitle || a.title || "").localeCompare(String(b.sortTitle || b.title || ""))
    return la < lb ? 1 : -1
  })
  var withPlayed = []
  for (var i = 0; i < copy.length; i++) {
    if (copy[i].lastPlayed)
      withPlayed.push(copy[i])
  }
  if (withPlayed.length)
    return withPlayed.slice(0, limit || 12)
  return copy.slice(0, limit || 12)
}

function launchArgv(game) {
  if (!game || !game.launch) return null
  var kind = game.launch.kind
  var value = game.launch.value
  if (kind === "uri")
    return ["xdg-open", String(value)]
  if (kind === "desktop")
    return ["gio", "launch", String(value)]
  if (kind === "argv") {
    if (value && value.length !== undefined && typeof value !== "string")
      return value.slice()
    return [String(value)]
  }
  return null
}

function initials(title) {
  var t = String(title || "").trim()
  if (!t.length) return "?"
  var parts = t.split(/\s+/)
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[1][0]).toUpperCase()
}
