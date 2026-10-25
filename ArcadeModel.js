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

function libraryEntries(games) {
  var out = []
  var list = games || []
  for (var i = 0; i < list.length; i++) {
    var g = list[i]
    if (g && g.id)
      out.push(g)
  }
  return out
}

function resolvedGames(service, localGames) {
  // library.json is the display source of truth. A keepLoaded service can
  // still hold a stale shorter list after a rescan (FileView miss on atomic replace).
  var cache = libraryEntries(localGames)
  var live = libraryEntries(service && service.games)
  if (!cache.length)
    return live
  if (!live.length)
    return cache
  var byId = {}
  var order = []
  function add(g, overwrite) {
    var id = String(g.id)
    if (!byId[id])
      order.push(id)
    if (overwrite || !byId[id])
      byId[id] = g
  }
  for (var i = 0; i < live.length; i++)
    add(live[i], false)
  for (var j = 0; j < cache.length; j++)
    add(cache[j], true)
  var out = []
  for (var k = 0; k < order.length; k++)
    out.push(byId[order[k]])
  return out
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
    if (!extra || typeof extra === "string" || alsoOnIsWrapper(extra))
      continue
    var label = sourceLabel(extra.source)
    if (label && !seen[label])
      add("Play on " + label)
  }
  return badges
}

function alsoOnIsWrapper(extra) {
  if (!extra) return false
  var extraId = String(extra.id || "")
  if (extraId.indexOf("desktop:steam:") === 0 || extraId.indexOf("steam_app_") === 0)
    return true
  var launch = extra.launch || {}
  var value = launch.value
  var text = typeof value === "string" ? value : (value && value.join ? value.join(" ") : "")
  if (String(text).indexOf("steam://rungameid/") !== -1)
    return true
  var track = extra.track || {}
  if (String(extra.source || "") === "desktop" && track.steamAppId)
    return true
  return false
}

function hasPlayOn(game) {
  return playOnChoices(game).length > 1
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

function playMeta(game, meta) {
  if (!game && !meta) return ""
  var last = (meta && meta.lastPlayed) || (game && game.lastPlayed)
  var minutes = (meta && meta.playtimeMinutes) || (game && game.playtimeMinutes)
  var parts = []
  var year = formatYear(meta && meta.releaseYear)
  var rating = formatRating(meta && meta.rating)
  var proton = protonLabel(meta && meta.proton)
  if (year) parts.push(year)
  if (rating) parts.push(rating)
  if (minutes) parts.push(formatPlaytime(minutes) + " played")
  if (last) parts.push("Last played " + formatLastPlayed(last))
  if (proton) parts.push(proton)
  return parts.join("  ·  ")
}

function heroUrl(game, meta) {
  if (meta && meta.art && meta.art.hero)
    return meta.art.hero
  if (game && game.art && game.art.hero)
    return game.art.hero
  return ""
}

function coverUrl(game, meta) {
  if (meta && meta.art && meta.art.cover)
    return meta.art.cover
  if (game && game.art && game.art.cover)
    return game.art.cover
  return ""
}

function lookupMeta(game, metaById) {
  if (!game || !game.id || !metaById)
    return null
  return metaById[game.id] || null
}

function rememberMeta(metaById, meta) {
  var next = {}
  var src = metaById || {}
  for (var key in src) {
    if (Object.prototype.hasOwnProperty.call(src, key))
      next[key] = src[key]
  }
  if (meta && meta.id)
    next[meta.id] = meta
  return next
}

function rememberMetaMap(metaById, entries) {
  var next = rememberMeta(metaById, null)
  if (!entries)
    return next
  for (var id in entries) {
    if (!Object.prototype.hasOwnProperty.call(entries, id))
      continue
    next = rememberMeta(next, entries[id])
  }
  return next
}

function isIconOnly(game) {
  return !!(game && game.art && game.art.iconOnly)
}

function hasMetaCover(meta) {
  return !!(meta && meta.art && meta.art.cover)
}

function isSmallArt(game, implicitW, implicitH, meta) {
  // Cached metadata cover is real box art (SGDB / IGDB), even when the
  // .desktop row still carries iconOnly and a BA placeholder.
  if (hasMetaCover(meta))
    return false
  var w = Number(implicitW) || 0
  var h = Number(implicitH) || 0
  // Measured pixels win over a stale iconOnly flag (GFN box art lives in Icon=).
  if (w > 0 || h > 0)
    return Math.max(w, h) < 256
  return isIconOnly(game)
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
    if (!a || typeof a === "string" || alsoOnIsWrapper(a))
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

function cacheStem(gameId) {
  var id = String(gameId || "").trim()
  if (!id.length) return ""
  return id.replace(/[^A-Za-z0-9._-]+/g, "_")
}

function metaFilePath(home, xdgCacheHome, gameId) {
  var stem = cacheStem(gameId)
  if (!stem.length) return ""
  return cacheDir(home, xdgCacheHome) + "/meta/" + stem + ".json"
}

function parseMetaText(text) {
  if (!text || !String(text).length)
    return {}
  try {
    var data = JSON.parse(text)
    return data && typeof data === "object" ? data : {}
  } catch (e) {
    return {}
  }
}

function metaIsFresh(meta) {
  if (!meta || !meta.fetchedAt) return false
  var fetched = Date.parse(meta.fetchedAt)
  if (isNaN(fetched)) return false
  var days = Number(meta.ttlDays || 14)
  if (!days) days = 14
  return (Date.now() - fetched) < days * 86400000
}

// Mirrors arcade/meta/resolve.py providers_at_fetch(): a cached record
// fetched before a key was added should refresh now, not after the TTL.
function providersAtFetch(meta) {
  var names = ["igdb", "steamgriddb"]
  var out = {}
  var stored = meta && meta.providers
  var used = (meta && meta.sourcesUsed) || []
  var errors = (meta && meta.errors) || []
  for (var i = 0; i < names.length; i++) {
    var name = names[i]
    if (stored && typeof stored === "object") {
      out[name] = !!stored[name]
      continue
    }
    var seen = used.indexOf(name) !== -1
    for (var j = 0; j < errors.length && !seen; j++) {
      if (String(errors[j]).indexOf(name + ":") === 0)
        seen = true
    }
    out[name] = seen
  }
  return out
}

function metaMissingProvider(meta, keyStatus) {
  if (!meta || !keyStatus) return false
  var seen = providersAtFetch(meta)
  return (!!keyStatus.igdb && !seen.igdb) || (!!keyStatus.steamgriddb && !seen.steamgriddb)
}

function sourceLabels(game) {
  if (!game) return []
  var out = [sourceLabel(game.source)]
  var extra = game.alsoOn || []
  for (var i = 0; i < extra.length; i++) {
    var a = extra[i]
    if (!a || typeof a === "string") continue
    var label = sourceLabel(a.source)
    if (label && out.indexOf(label) === -1)
      out.push(label)
  }
  return out.filter(function(s) { return !!s })
}

function metaChips(meta) {
  var out = []
  if (!meta) return out
  var genres = meta.genres || []
  var developers = meta.developers || []
  var i
  for (i = 0; i < genres.length && out.length < 4; i++) {
    if (genres[i] && out.indexOf(genres[i]) === -1)
      out.push(genres[i])
  }
  for (i = 0; i < developers.length && out.length < 6; i++) {
    if (developers[i] && out.indexOf(developers[i]) === -1)
      out.push(developers[i])
  }
  return out
}

function formatRating(rating) {
  if (!rating || rating.score == null) return ""
  var score = String(rating.label || rating.score)
  var source = String(rating.source || "")
  if (source === "metacritic") return score + " Metacritic"
  if (source === "igdb") return score + " IGDB"
  return score
}

function formatYear(year) {
  if (year == null || year === "") return ""
  var n = Number(year)
  if (!n) return ""
  return String(n)
}

function protonLabel(proton) {
  if (!proton || !proton.tier) return ""
  var tier = String(proton.tier)
  return "ProtonDB " + tier.charAt(0).toUpperCase() + tier.slice(1)
}

function descriptionText(game, meta) {
  var fromMeta = meta && meta.description ? String(meta.description).trim() : ""
  if (fromMeta.length) return fromMeta
  var raw = game && game.description ? String(game.description).trim() : ""
  if (!raw.length) return ""
  var skip = ["steam", "ubisoft", "epic", "gog", "amazon", "geforce now", "gfn"]
  if (skip.indexOf(raw.toLowerCase()) !== -1) return ""
  return raw
}

function playtimeMinutesOf(game, meta) {
  if (meta && meta.playtimeMinutes) return meta.playtimeMinutes
  return game ? game.playtimeMinutes : null
}

function lastPlayedOf(game, meta) {
  if (meta && meta.lastPlayed) return meta.lastPlayed
  return game ? game.lastPlayed : null
}

function factsLine(game, meta) {
  return playMeta(game, meta)
}
