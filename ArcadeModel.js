.pragma library

function pluginId(manifest) {
  return (manifest && manifest.id) ? manifest.id : "matt-dance.arcade"
}

function cacheDir(home, xdgCacheHome) {
  var xdg = xdgCacheHome || ""
  var h = home || ""
  var base = (xdg && xdg.length) ? xdg : (h + "/.cache")
  return base + "/matt-dance.arcade"
}

function libraryFilePath(home, xdgCacheHome) {
  return cacheDir(home, xdgCacheHome) + "/library.json"
}

function pluginDirPath(home, manifest) {
  return String(home || "") + "/.config/omarchy/plugins/" + pluginId(manifest)
}

function parseLibraryText(text) {
  if (!text || !String(text).length)
    return { games: [], errors: [], ok: true, empty: true }
  try {
    var data = JSON.parse(text)
    var games = data.games || []
    return {
      games: games,
      errors: data.errors || [],
      ok: true,
      empty: games.length === 0
    }
  } catch (e) {
    return { games: [], errors: [], ok: false, empty: true, error: String(e) }
  }
}

function resolvedGames(service, localGames) {
  if (service && service.games && service.games.length)
    return service.games
  return localGames || []
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
    moonlight: "Moonlight",
    gog: "GOG",
    epic: "Epic",
    amazon: "Amazon"
  }
  var key = String(source || "").toLowerCase()
  return map[key] || source || ""
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

function homeShelf(games) {
  var items = (games || []).slice()
  var played = []
  var rest = []
  for (var i = 0; i < items.length; i++) {
    if (items[i].lastPlayed)
      played.push(items[i])
    else
      rest.push(items[i])
  }
  function byTitle(a, b) {
    return String(a.sortTitle || a.title || "").localeCompare(String(b.sortTitle || b.title || ""))
  }
  played.sort(byTitle)
  played.sort(function(a, b) {
    var la = a.lastPlayed || ""
    var lb = b.lastPlayed || ""
    if (la === lb) return 0
    return la < lb ? 1 : -1
  })
  rest.sort(byTitle)
  return played.concat(rest)
}

function sourceBadges(game) {
  if (!game) return []
  var badges = []
  var seen = {}
  function add(label) {
    if (!label || seen[label]) return
    seen[label] = true
    badges.push(label)
  }
  add(sourceLabel(game.source))
  if (game.store)
    add(sourceLabel(game.store))
  var extras = game.alsoOn || []
  for (var i = 0; i < extras.length; i++) {
    var extra = extras[i]
    if (!extra || typeof extra === "string")
      continue
    var label = sourceLabel(extra.source)
    if (label && !seen[label])
      add("Play on " + label)
  }
  return badges
}

function formatPlaytime(minutes) {
  if (minutes === undefined || minutes === null || minutes === "")
    return ""
  var n = Number(minutes)
  if (isNaN(n) || n < 0)
    return ""
  if (n < 60)
    return Math.round(n) + " min"
  var hours = n / 60
  if (hours < 10)
    return (Math.round(hours * 10) / 10) + " h"
  return Math.round(hours) + " h"
}

function formatLastPlayed(iso) {
  if (!iso) return ""
  var day = String(iso).slice(0, 10)
  if (day.length < 10 || day[4] !== "-" || day[7] !== "-")
    return String(iso)
  var months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
  var month = parseInt(day.slice(5, 7), 10)
  var d = parseInt(day.slice(8, 10), 10)
  if (!month || month < 1 || month > 12 || !d)
    return day
  return months[month - 1] + " " + d + ", " + day.slice(0, 4)
}

function playMeta(game) {
  if (!game) return ""
  if (game.lastPlayed)
    return "Last played " + formatLastPlayed(game.lastPlayed)
  if (game.playtimeMinutes)
    return formatPlaytime(game.playtimeMinutes) + " played"
  return ""
}

function heroUrl(game) {
  if (game && game.art && game.art.hero)
    return game.art.hero
  return ""
}

function coverUrl(game) {
  if (game && game.art && game.art.cover)
    return game.art.cover
  return ""
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

function playOnChoices(game) {
  if (!game) return []
  var out = [{
    id: game.id,
    source: game.source,
    store: game.store,
    title: game.title,
    launch: game.launch,
    track: game.track,
    label: sourceLabel(game.source)
  }]
  var extra = game.alsoOn || []
  for (var i = 0; i < extra.length; i++) {
    var a = extra[i]
    if (!a || typeof a === "string")
      continue
    out.push({
      id: a.id || game.id,
      source: a.source || "",
      store: a.store,
      title: a.title || game.title,
      launch: a.launch,
      track: a.track,
      label: sourceLabel(a.source)
    })
  }
  return out
}

function initials(title) {
  var t = String(title || "").trim()
  if (!t.length) return "?"
  var parts = t.split(/\s+/)
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[1][0]).toUpperCase()
}
