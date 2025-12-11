using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

namespace CyNiTLauncherApp
{
    static class Program
    {
        [STAThread]
        public static void Main(string[] args)
        {
            // Pad naar de map waar ctools.py staat
            string baseDir = @"C:\gh\CyNiT-tools\CyNiT-tools\CyNiT-tools";

            // Als Python in PATH staat, is dit genoeg:
            // string pythonExe = "python.exe";

            // Gebruik desnoods het volledige pad naar python.exe:
            string pythonExe = @"python.exe";

            string scriptPath = Path.Combine(baseDir, "ctools.py");

            try
            {
                if (!File.Exists(scriptPath))
                {
                    throw new FileNotFoundException("ctools.py werd niet gevonden op: " + scriptPath);
                }

                var psi = new ProcessStartInfo();
                psi.FileName = pythonExe;
                psi.Arguments = "\"" + scriptPath + "\"";
                psi.WorkingDirectory = baseDir;
                psi.UseShellExecute = false;
                psi.CreateNoWindow = true;
                psi.WindowStyle = ProcessWindowStyle.Hidden;

                Process.Start(psi);
            }
            catch (Exception ex)
            {
                MessageBox.Show(
                    "CyNiT Tools kon niet worden gestart:\n\n" + ex.Message,
                    "CyNiT Tools – fout",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Error
                );
            }
        }
    }
}
