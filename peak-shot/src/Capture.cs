// PeakShot - MIT License (c) 2026 peakmaptoday.org
using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using Peak;
using Photon.Pun;
using UnityEngine;
using Zorro.Core;
using Object = UnityEngine.Object;

namespace PeakShot
{
    class Marker
    {
        public int Id; public string Category, Name, Display; public Vector3 Pos; public Component Ref;
    }

    class View
    {
        public string Id, Image; public Vector3 Pos, Euler; public float Fov;
        public List<(Marker m, Vector2 px)> Hits = new List<(Marker, Vector2)>();
    }

    class Capture
    {
        const int Segs = 5;
        readonly string _scene, _dir;
        readonly int W, H, Q;
        readonly Dictionary<int, Marker> _markers = new Dictionary<int, Marker>();
        readonly float[] _width = new float[Segs];
        readonly float[] _height = new float[Segs];
        readonly Vector3?[] _cf = new Vector3?[Segs];
        readonly StringBuilder _json = new StringBuilder();
        int _swamp, _volcano;

        public Capture(string scene, string dir)
        {
            _scene = scene; _dir = dir;
            W = Plugin.Instance.Width.Value; H = Plugin.Instance.Height.Value; Q = Plugin.Instance.Quality.Value;
        }

        static MapHandler.MapSegment Seg(int i)
        {
            var s = Singleton<MapHandler>.Instance?.segments;
            return s != null && i < s.Length ? s[i] : null;
        }

        static string F(float f) => f.ToString("0.####", CultureInfo.InvariantCulture);
        static string V(Vector3 v) => "[" + F(v.x) + "," + F(v.y) + "," + F(v.z) + "]";
        static string S(string s) => "\"" + (s ?? "").Replace("\\", "\\\\").Replace("\"", "\\\"") + "\"";

        // ---------- marker discovery (scan-based, deduped by instance id) ----------
        void Add(Component c, string cat, string name, string display, Vector3? pos = null)
        {
            int id = c.GetInstanceID();
            if (_markers.ContainsKey(id)) return;
            _markers[id] = new Marker { Id = id, Category = cat, Name = name, Display = display, Pos = pos ?? c.transform.position, Ref = c };
        }

        void ScanStatic()
        {
            LocalizedText.SetLanguage((int)LocalizedText.Language.English);
            foreach (var l in Object.FindObjectsByType<Luggage>(FindObjectsInactive.Include, FindObjectsSortMode.None))
                Add(l, l is RespawnChest ? "respawn" : "luggage", l.name, SafeName(l));
            foreach (var a in Object.FindObjectsByType<FakeItem>(FindObjectsInactive.Include, FindObjectsSortMode.None)
                         .Where(n => n.name.ToLowerInvariant().Contains("amulet")))
                Add(a, "amulet", a.itemName, SafeFakeName(a));
            foreach (var t in Object.FindObjectsByType<Transform>(FindObjectsInactive.Include, FindObjectsSortMode.None)
                         .Where(n => n.name == "AntlionHead"))
                Add(t, "critter", "Antlion", "ANTLION");
            FindTomb();
        }

        // things that only count once they are actually live in the scene
        void ScanLive()
        {
            foreach (var l in Object.FindObjectsByType<Luggage>(FindObjectsInactive.Include, FindObjectsSortMode.None))
                Add(l, l is RespawnChest ? "respawn" : "luggage", l.name, SafeName(l));
            foreach (var g in Object.FindObjectsByType<GhostFire>(FindObjectsSortMode.None))
                Add(g, "belltower", g.name, "BELLTOWER");
            foreach (var c in Object.FindObjectsByType<Capybara>(FindObjectsSortMode.None))
                Add(c, "critter", "Capybara", "CAPYBARA");
            foreach (var w in Object.FindObjectsByType<EarlyWorm>(FindObjectsSortMode.None))
                Add(w, "critter", "EarlyWorm", "EARLY WORM");
            foreach (var b in Object.FindObjectsByType<Beehive>(FindObjectsSortMode.None))
                Add(b, "critter", "Beehive", "BEEHIVE");
        }

        static string SafeName(Luggage l) { try { return l.GetName(); } catch { return l.name; } }
        static string SafeFakeName(FakeItem f) { try { return f.GetName(); } catch { return f.itemName; } }

        void FindTomb()
        {
            var seg = Seg(2);
            if (seg == null || seg.biome != Biome.BiomeType.Mesa || seg.segmentParent == null) return;
            Transform cur = seg.segmentParent.transform;
            foreach (var n in new[] { "Desert_Segment", "Platteau", "Rocks", "Timple", "Enterences", "2" })
            {
                cur = cur?.GetComponentsInChildren<Transform>(true).FirstOrDefault(t => t.name == n);
                if (cur == null) { Plugin.Log.LogWarning("Tomb path missing at " + n); return; }
            }
            if (cur.childCount == 0 || cur.GetChild(0).childCount != 2) { Plugin.Log.LogInfo("Tomb closed"); return; }
            Add(cur, "tomb", "Tomb", "TOMB");
        }

        // ---------- layout ----------
        void Dimensions()
        {
            _width[4] = 5000; _height[4] = 5000;
            for (int i = 0; i < Segs; i++)
            {
                var seg = Seg(i);
                Vector3? cf = seg?.segmentCampfire != null ? seg.segmentCampfire.transform.position : (Vector3?)null;
                if (cf == null) continue;
                if (i == 3 && seg.biome == Biome.BiomeType.Volcano)
                {
                    // Kiln: the real "end" is the furthest scout statue
                    var st = _markers.Values.Where(m => m.Category != "amulet" && (m.Name ?? "").ToLowerInvariant() == "scout statue")
                        .OrderByDescending(m => m.Pos.z).FirstOrDefault();
                    if (st != null) cf = st.Pos + new Vector3(0, 0, 250f);
                    else Plugin.Log.LogWarning("Kiln: no scout statue found, using campfire");
                }
                _cf[i] = cf;
                _width[i] = cf.Value.z + 10f;
                _height[i] = cf.Value.y;
            }
        }

        View Front(int i)
        {
            Vector3 c(int k) => _cf[k] ?? Vector3.zero;
            switch (i)
            {
                case 0: return new View { Id = "front", Pos = new Vector3(0, 100, -500), Euler = Vector3.zero, Fov = 45 };
                case 1: return new View { Id = "front", Pos = new Vector3(0, c(0).y + 200, c(0).z + 100), Euler = new Vector3(30, 0, 0), Fov = 90 };
                case 2: return new View { Id = "front", Pos = new Vector3(0, c(1).y + 100, c(1).z + 25), Euler = new Vector3(23, 0, 0), Fov = 90 };
                case 3: return new View { Id = "front", Pos = new Vector3(0, c(2).y + 200, c(2).z + 375), Euler = new Vector3(89.9f, -89.9f, 0), Fov = 90 };
                default: return new View { Id = "front", Pos = new Vector3(0, c(3).y + 220, c(3).z - 125), Euler = Vector3.zero, Fov = 90 };
            }
        }

        View Side(int i)
        {
            float prev = i > 0 ? _width[i - 1] : -200f;
            return new View { Id = "side", Pos = new Vector3(280, _height[i] + 100, (prev + _width[i]) / 2f), Euler = new Vector3(45, -90, 0), Fov = 60 };
        }

        // ---------- scene prep ----------
        EnablingSubstep[] Prepare(MapHandler.MapSegment seg)
        {
            PhotonNetwork.IsMessageQueueRunning = false;
            var parent = seg.segmentParent;
            var subs = parent.GetComponentsInChildren<EnablingSubstep>(true).Where(s => s.gameObject.activeSelf).ToArray();
            parent.SetActive(true);
            foreach (var s in subs) s.gameObject.SetActive(true);
            if (seg.segmentCampfire != null) seg.segmentCampfire.SetActive(true);
            if (seg.wallNext != null) seg.wallNext.SetActive(false);
            if (seg.wallPrevious != null) seg.wallPrevious.SetActive(false);
            if (seg.biome == Biome.BiomeType.Swamp) _swamp++;
            else if (seg.biome == Biome.BiomeType.Volcano) _volcano++;
            if (_swamp == 2) DestroyWhere(n => n.Contains("gloom temple"), true);
            if (_volcano == 2)
            {
                DestroyWhere(n => n == "volcanomodel", true);
                DestroyWhere(n => n.Contains("rock_round") || n.Contains("rockfinal"), false);
            }
            PhotonNetwork.IsMessageQueueRunning = true;
            return subs;
        }

        static void DestroyWhere(Func<string, bool> pred, bool firstOnly)
        {
            var hits = Object.FindObjectsByType<Transform>(FindObjectsInactive.Include, FindObjectsSortMode.None)
                .Where(t => t != null && pred(t.gameObject.name.ToLowerInvariant())).ToList();
            if (firstOnly) hits = hits.Take(1).ToList();
            foreach (var t in hits)
                if (t != null) { Plugin.Log.LogInfo("Removing " + t.gameObject.name); Object.DestroyImmediate(t.gameObject); }
        }

        // ---------- rendering ----------
        Camera MakeCam(View v)
        {
            var go = new GameObject("PeakShotCam");
            go.transform.position = v.Pos; go.transform.eulerAngles = v.Euler;
            var cam = go.AddComponent<Camera>();
            cam.enabled = false;
            cam.clearFlags = CameraClearFlags.Skybox;
            cam.fieldOfView = v.Fov;
            cam.aspect = (float)W / H;
            return cam;
        }

        bool Render(Camera cam, string path)
        {
            RenderTexture rt = null; Texture2D tex = null;
            try
            {
                rt = new RenderTexture(W, H, 24);
                if (!rt.Create()) { Plugin.Log.LogError("RenderTexture create failed " + W + "x" + H); return false; }
                cam.targetTexture = rt;
                cam.Render();
                RenderTexture.active = rt;
                tex = new Texture2D(W, H, TextureFormat.RGB24, false);
                tex.ReadPixels(new Rect(0, 0, W, H), 0, 0);
                tex.Apply();
                File.WriteAllBytes(path, tex.EncodeToJPG(Q));
                return true;
            }
            catch (Exception e) { Plugin.Log.LogError("Render failed: " + e); return false; }
            finally
            {
                cam.targetTexture = null; RenderTexture.active = null;
                if (rt != null) Object.DestroyImmediate(rt);
                if (tex != null) Object.DestroyImmediate(tex);
            }
        }

        void Project(int i, View v, Camera cam)
        {
            float prev = i > 0 ? _width[i - 1] : -500f;
            foreach (var m in _markers.Values)
            {
                if (m.Category == "luggage" || m.Category == "respawn")
                    if (m.Ref == null || !m.Ref.gameObject.activeInHierarchy) continue;
                if (!(m.Pos.z <= _width[i] && m.Pos.z > prev && m.Pos.y <= _height[i] + 10f)) continue;
                Vector3 vp = cam.WorldToViewportPoint(m.Pos);
                if (vp.z <= 0 || vp.x < 0 || vp.x > 1 || vp.y < 0 || vp.y > 1) continue;
                v.Hits.Add((m, new Vector2(vp.x * W, H - vp.y * H)));
            }
        }

        public IEnumerator Run()
        {
            var log = Plugin.Log;
            ScanStatic();
            Dimensions();
            var segJson = new List<string>();
            for (int i = 0; i < Segs; i++)
            {
                var seg = Seg(i);
                if (seg == null || seg.segmentParent == null) { log.LogWarning("Segment " + i + " missing"); continue; }
                var subs = Prepare(seg);
                yield return null; // let OnEnable/Start settle for one frame
                var views = new List<View> { Front(i) };
                if (i < 3) views.Add(Side(i));
                var cams = new List<Camera>();
                foreach (var v in views)
                {
                    v.Image = "level_" + i + (v.Id == "side" ? "_side" : "") + ".jpg";
                    var cam = MakeCam(v); cams.Add(cam);
                    log.LogInfo($"{_scene} seg{i} {v.Id} pos={v.Pos} euler={v.Euler} fov={v.Fov}");
                    if (!Render(cam, Path.Combine(_dir, v.Image))) v.Image = null;
                    yield return null;
                }
                foreach (var sp in seg.segmentParent.GetComponentsInChildren<ISpawner>(true))
                {
                    try { sp.TrySpawnItems(); } catch (Exception e) { log.LogWarning("spawn: " + e.Message); }
                }
                yield return null;
                ScanLive();
                for (int k = 0; k < views.Count; k++) { Project(i, views[k], cams[k]); Object.Destroy(cams[k].gameObject); }
                segJson.Add(SegmentJson(i, seg, views));
                seg.segmentParent.SetActive(false);
                foreach (var s in subs) if (s != null) s.gameObject.SetActive(false);
                yield return null;
            }
            var sb = new StringBuilder();
            sb.Append("{\"format\":\"peakshot/1\",\"scene\":").Append(S(_scene))
              .Append(",\"gameVersion\":").Append(S(Application.version))
              .Append(",\"capturedUtc\":").Append(S(DateTime.UtcNow.ToString("o")))
              .Append(",\"width\":").Append(W).Append(",\"height\":").Append(H)
              .Append(",\"segments\":[").Append(string.Join(",", segJson)).Append("]}");
            File.WriteAllText(Path.Combine(_dir, "level.json"), sb.ToString());
            log.LogInfo("Wrote " + Path.Combine(_dir, "level.json"));
        }

        string SegmentJson(int i, MapHandler.MapSegment seg, List<View> views)
        {
            var vs = views.Select(v =>
            {
                var ms = v.Hits.Select(h =>
                    "{\"category\":" + S(h.m.Category) + ",\"name\":" + S(h.m.Name) + ",\"displayName\":" + S(h.m.Display) +
                    ",\"world\":" + V(h.m.Pos) + ",\"px\":[" + F(h.px.x) + "," + F(h.px.y) + "]" +
                    ",\"x\":" + F(h.px.x / W) + ",\"y\":" + F(h.px.y / H) + "}");
                return "{\"id\":" + S(v.Id) + ",\"image\":" + (v.Image == null ? "null" : S(v.Image)) +
                       ",\"camera\":{\"pos\":" + V(v.Pos) + ",\"euler\":" + V(v.Euler) + ",\"fov\":" + F(v.Fov) + "}" +
                       ",\"markers\":[" + string.Join(",", ms) + "]}";
            });
            return "{\"index\":" + i + ",\"biome\":" + S(seg.biome.ToString()) +
                   ",\"campfire\":" + (_cf[i].HasValue ? V(_cf[i].Value) : "null") +
                   ",\"zMax\":" + F(_width[i]) + ",\"yMax\":" + F(_height[i] + 10f) +
                   ",\"views\":[" + string.Join(",", vs) + "]}";
        }
    }
}
