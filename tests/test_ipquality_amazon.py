"""Exercise the actual shell hotfix with upstream-shaped local scripts."""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from test_ansi_integration import bot, SERVER, RAW, URL

BUGGY = "local result=$(echo $tmpresult|grep '\"currentTerritory\":'|sed 's/.*currentTerritory//'|cut -f3 -d'\"'|head -n 1)"
UPSTREAM = '''#!/bin/bash
declare -A amazon smedia=([bad]=unknown [nodata]=--)
function check_amazon(){
local tmpresult="$RESPONSE"
PARSER
if [ -n "$result" ];then
amazon[ustatus]=yes
amazon[uregion]="  [$result]   "
else
amazon[ustatus]=no
amazon[uregion]=--
fi
}
check_amazon
printf '%s|%s' "${amazon[ustatus]}" "${amazon[uregion]}"
'''.replace('PARSER', BUGGY)

class AmazonParserTest(unittest.TestCase):
    def run_hotfix(self, response, source=UPSTREAM):
        definition = getattr(bot, 'ipquality_hotfix_definition', lambda: '')()
        with tempfile.TemporaryDirectory() as td:
            script=Path(td)/'upstream.sh';script.write_text(source)
            # Only curl is stubbed; patching and the resulting Bash parser run.
            command='curl() { /bin/cat '+shlex.quote(str(script))+'; }; '+definition+' guko_ipquality_script | bash'
            return subprocess.run(['bash','-o','pipefail','-c',command],env={**os.environ,'RESPONSE':response},text=True,capture_output=True)

    def test_real_shaped_page_ignores_later_javascript_property(self):
        response='{"currentTerritory":"JP"};let t={currentTerritory:null},Program:{dataType:a.MinervaValueDataType.STRING,val:o?"};'
        result=self.run_hotfix(response)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout,'yes|  [JP]   ')

    def test_missing_invalid_and_code_values_are_unknown_not_region(self):
        for response in ['{"currentTerritory":null}', '{"currentTerritory":"JPN"}', '{"currentTerritory":"<script>bad</script>"}', 'blocked page']:
            with self.subTest(response=response):
                result=self.run_hotfix(response)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(result.stdout,'unknown|--')

    def test_whitespace_newlines_and_other_valid_territories(self):
        result=self.run_hotfix('{"currentTerritory" :\n "US"}')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout,'yes|  [US]   ')

    def test_upstream_drift_fails_instead_of_running_unpatched(self):
        result=self.run_hotfix('{}','printf unsafe-source-ran')
        self.assertNotEqual(result.returncode,0)
        self.assertNotIn('unsafe-source-ran',result.stdout)

    def test_nq_ip_path_exports_and_uses_same_filter(self):
        command=bot.nodequality_remote_command(SERVER,2)
        self.assertIn('export -f guko_ipquality_script',command)
        self.assertIn('guko_ipquality_script',command)
        self.assertIn('script_text=',command)
        syntax=subprocess.run(['bash','-n','-c',command],capture_output=True,text=True)
        self.assertEqual(syntax.returncode,0,syntax.stderr)
        self.assertNotIn('guko_ipquality_script',bot.nodequality_remote_command(SERVER,1))

    def test_nq_child_shell_executes_filtered_ip_script(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td)
            ip=td/'ip.sh';ip.write_text(UPSTREAM)
            nq=td/'nq.sh';nq.write_text('''#!/bin/bash
chroot_run() { "$@"; }
chroot_run bash <(curl -Ls https://IP.Check.Place) $opt_ipv $opt_lang -y -o /result/$ip_quality_json_filename
''')
            curl=td/'curl'
            curl.write_text('''#!/bin/bash
while [ "$#" -gt 0 ]; do
if [ "$1" = -o ]; then /bin/cp "$NQ_FIXTURE" "$2"; exit; fi
shift
done
/bin/cat "$IP_FIXTURE"
''');curl.chmod(0o700)
            command=bot.nodequality_remote_command(SERVER,2).replace('/root/nodequality.XXXXXX.sh',str(td/'nodequality.XXXXXX.sh'))
            result=subprocess.run(['bash','-c',command],env={**os.environ,'PATH':str(td)+':'+os.environ['PATH'],'NQ_FIXTURE':str(nq),'IP_FIXTURE':str(ip),'RESPONSE':'{"currentTerritory":"JP"};x={currentTerritory:null}'},capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(result.stdout,'yes|  [JP]   ')

    def test_standalone_task_uses_same_filter(self):
        bot.JOBS['amazon-test']={}
        import asyncio
        from types import SimpleNamespace
        tg=SimpleNamespace(send_message=AsyncMock(),send_photo=AsyncMock())
        with patch.object(bot,'run_until_report',AsyncMock(return_value=(1,'no report',None))) as run, patch.object(bot,'finish_job'), patch.object(bot,'ssh_args',side_effect=lambda s,cmd,**kw:['ssh',cmd]):
            asyncio.run(bot.run_ip_quality_task(tg,1,SERVER,'amazon-test'))
        command=run.await_args.args[0][-1]
        self.assertIn('bash <(guko_ipquality_script) -y',command)
        self.assertIn('export -f guko_ipquality_script',command)
        bot.JOBS.pop('amazon-test',None)
