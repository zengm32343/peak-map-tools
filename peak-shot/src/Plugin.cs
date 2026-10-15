// PeakShot - MIT License (c) 2026 peakmaptoday.org
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using BepInEx;
using BepInEx.Configuration;
using BepInEx.Logging;
using HarmonyLib;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace PeakShot
{
    [BepInPlugin("org.peakmaptoday.peakshot", "PeakShot", "0.1.0")]
    public class Plugin : BaseUnityPlugin
    {
        internal static ManualLogSource Log;
        internal static Plugin Instance;
        internal static string PendingScene;

        ConfigEntry<bool> _enabled;
        ConfigEntry<string> _outDir, _levels;
        internal ConfigEntry<int> Width, Height, Quality;

        readonly Queue<string> _queue = new Queue<string>();
        float _cooldown;
        bool _busy;
        string _state = "init";

        void Awake()
        {
            Instance = this; Log = Logger;
            _enabled = Config.Bind("General", "Enabled", false, "Automate offline capture on startup (the game quits when done). Keep false to play normally.");
            _outDir = Config.Bind("General", "OutputDir", Path.Combine(Paths.GameRootPath, "peakshot-out"), "Output folder");
            _levels = Config.Bind("General", "Levels", "Level_3", "Comma separated scenes (e.g. Level_3,Level_4) or ALL");
            Width = Config.Bind("Render", "Width", 7680, "");
            Height = Config.Bind("Render", "Height", 4320, "");
            Quality = Config.Bind("Render", "JpgQuality", 92, "");
            if (!_enabled.Value) { Log.LogInfo("PeakShot disabled"); return; }
            new Harmony("org.peakmaptoday.peakshot").PatchAll(typeof(Plugin).Assembly);
            Log.LogInfo("PeakShot loaded, levels=" + _levels.Value);
        }

        bool _queueBuilt;
        void BuildQueue()
        {
            var all = new List<string>();
            for (int i = 0; i < SceneManager.sceneCountInBuildSettings; i++)
            {
                string p = SceneUtility.GetScenePathByBuildIndex(i);
                int k = p.IndexOf("/Generated/");
                if (k >= 0) all.Add(Path.GetFileNameWithoutExtension(p));
            }
            Log.LogInfo("Generated scenes: " + string.Join(",", all));
            var want = _levels.Value.Trim();
            IEnumerable<string> sel = want.ToUpperInvariant() == "ALL" ? all
                : want.Split(',').Select(s => s.Trim()).Where(s => all.Contains(s));
            foreach (var s in sel) _queue.Enqueue(s);
            _queueBuilt = true;
        }

        void Update()
        {
            if (!_enabled.Value || _busy) return;
            _cooldown -= Time.unscaledDeltaTime;
            if (_cooldown > 0 || LoadingScreenHandler.loading) return;
            if (!_queueBuilt) BuildQueue();

            var menu = Object.FindFirstObjectByType<MainMenu>();
            if (menu != null)
            {
                if (_queue.Count == 0 && PendingScene == null) { Log.LogInfo("All done, quitting"); Application.Quit(); _busy = true; return; }
                Log.LogInfo("Main menu -> solo session");
                AccessTools.Method(typeof(MainMenu), "StartSoloSession").Invoke(menu, null);
                _cooldown = 5; return;
            }
            string scene = SceneManager.GetActiveScene().name;
            if (scene == "Airport")
            {
                if (Character.localCharacter == null) return;
                if (_queue.Count == 0) { Log.LogInfo("All done, quitting"); Application.Quit(); _busy = true; return; }
                var kiosk = Object.FindFirstObjectByType<AirportCheckInKiosk>(FindObjectsInactive.Include);
                if (kiosk == null) return;
                PendingScene = _queue.Dequeue();
                Log.LogInfo("Kiosk -> " + PendingScene);
                kiosk.StartGame(0);
                _cooldown = 5; return;
            }
            if (PendingScene != null && scene == PendingScene && Character.localCharacter != null)
            {
                _busy = true;
                StartCoroutine(CaptureThenLeave(PendingScene));
            }
        }

        IEnumerator CaptureThenLeave(string scene)
        {
            yield return new WaitForSecondsRealtime(4f);
            string dir = Path.Combine(_outDir.Value, scene);
            Directory.CreateDirectory(dir);
            var cap = new Capture(scene, dir);
            yield return cap.Run();
            PendingScene = null;
            Log.LogInfo("Finished " + scene + ", leaving");
            GameHandler.GetService<ConnectionService>().StateMachine.SwitchState<DisconnectingState>();
            NetworkConnector.LeaveRoom();
            _cooldown = 5;
            _busy = false;
        }
    }

    [HarmonyPatch(typeof(AirportCheckInKiosk), nameof(AirportCheckInKiosk.BeginIslandLoadRPC))]
    static class KioskPatch
    {
        static void Prefix(ref string sceneName)
        {
            if (Plugin.PendingScene != null)
            {
                Plugin.Log.LogInfo("Redirect " + sceneName + " -> " + Plugin.PendingScene);
                sceneName = Plugin.PendingScene;
            }
        }
    }
}
