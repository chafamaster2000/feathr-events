// AgentLog — NDJSON structured logging for the agent logs contract (skill expose-hidden-logs).
// Escribe .logs/agent/<yyyy-MM-dd>/<taskId>.log en la raíz del repo (game/Assets → ../../.logs).
// La fecha del directorio es LOCAL, alineada con read-hidden-logs (date +%F) y con ProbeCapture;
// el timestamp de cada línea es ISO-8601 UTC.
// Uso: AgentLog.SetTask("issue-42"); AgentLog.Info("oxygen.tick", "drain applied", ("rate", 1.5f));
// Editor + Development Build only: compila a no-op en release (UNITY_EDITOR || DEVELOPMENT_BUILD).
using System;
using System.Globalization;
using System.IO;
using System.Text;

namespace Game.Infrastructure
{
    public static class AgentLog
    {
        private static string _taskId = "untracked";
        private static string _dir;

        public static void SetTask(string taskId) => _taskId = string.IsNullOrEmpty(taskId) ? "untracked" : taskId;

        public static void Info(string scope, string msg, params (string key, object value)[] ctx)  => Write("info", scope, msg, ctx);
        public static void Warn(string scope, string msg, params (string key, object value)[] ctx)  => Write("warn", scope, msg, ctx);
        public static void Error(string scope, string msg, params (string key, object value)[] ctx) => Write("error", scope, msg, ctx);

        private static void Write(string level, string scope, string msg, (string key, object value)[] ctx)
        {
#if UNITY_EDITOR || DEVELOPMENT_BUILD
            try
            {
                if (_dir == null)
                {
                    var root = Path.GetFullPath(Path.Combine(UnityEngine.Application.dataPath, "..", ".."));
                    _dir = Path.Combine(root, ".logs", "agent",
                        DateTime.Now.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture));
                    Directory.CreateDirectory(_dir);
                }
                var sb = new StringBuilder(256);
                sb.Append("{\"ts\":\"").Append(DateTime.UtcNow.ToString("o", CultureInfo.InvariantCulture))
                  .Append("\",\"level\":\"").Append(level)
                  .Append("\",\"scope\":\"").Append(Escape(scope))
                  .Append("\",\"taskId\":\"").Append(Escape(_taskId))
                  .Append("\",\"msg\":\"").Append(Escape(msg)).Append('"');
                if (ctx != null && ctx.Length > 0)
                {
                    sb.Append(",\"ctx\":{");
                    for (var i = 0; i < ctx.Length; i++)
                    {
                        if (i > 0) sb.Append(',');
                        sb.Append('"').Append(Escape(ctx[i].key)).Append("\":\"")
                          .Append(Escape(Convert.ToString(ctx[i].value, CultureInfo.InvariantCulture))).Append('"');
                    }
                    sb.Append('}');
                }
                sb.Append('}');
                File.AppendAllText(Path.Combine(_dir, _taskId + ".log"), sb.ToString() + Environment.NewLine);
            }
            catch { /* la evidencia nunca tira el juego */ }
#endif
        }

        private static string Escape(string s) =>
            string.IsNullOrEmpty(s) ? "" : s.Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\n", "\\n");
    }
}
