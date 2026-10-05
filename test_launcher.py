"""Shell error-handling checks with stub executables; no hardware access."""
import os
import shutil
import subprocess
import tempfile
import unittest
HERE=os.path.dirname(os.path.abspath(__file__))
SCRIPT=os.path.join(HERE,'spindle-test.sh')
class LauncherTests(unittest.TestCase):
    def test_source_guard(self):
        result=subprocess.check_output(['bash','-c',
            'before="$-"; source "$1" check; [ "$before" = "$-" ]; echo shell-still-active',
            'test',SCRIPT],stderr=subprocess.STDOUT).decode()
        self.assertIn('Do not source',result)
        self.assertIn('shell-still-active',result)
    def test_hold_requires_interactive_terminal(self):
        proc=subprocess.Popen(['bash',SCRIPT,'hold'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        output=proc.communicate()[0].decode()
        self.assertEqual(proc.returncode,1)
        self.assertIn('interactive terminal',output)

    def test_zero_mask_is_accepted_without_writes(self):
        root=tempfile.mkdtemp()
        try:
            for d in ('bin','scripts'):os.mkdir(os.path.join(root,d))
            body='[[ "$EMC2_BIN_DIR" == "$PP_ROOT/bin" && "$EMC2_RTLIB_DIR" == "$PP_ROOT/rtlib" && "$HAL_RTMOD_DIR" == "$PP_ROOT/rtlib" ]] || exit 9\ncase "$7:$8" in\n0x1018:1) echo \'0x00100000 1048576\';;\n0x1018:2) echo \'0x000c0130 786736\';;\n0x2004:3) echo \'0x000b 11\';;\n0x2004:4) echo \'0x0001 1\';;\n*) echo \'0x00000000 0\';;\nesac\n'
            for path,text in [('bin/halcmd','exit 0'),('scripts/py3_run.sh','exit 0'),('bin/ethercat',body)]:
                dest=os.path.join(root,path)
                with open(dest,'w') as f:f.write('#!/bin/bash\n'+text+'\n')
                os.chmod(dest,0o755)
            env=os.environ.copy();env['PP_ROOT']=root
            proc=subprocess.Popen(['bash',SCRIPT,'check'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,env=env)
            output=proc.communicate()[0].decode()
            self.assertEqual(proc.returncode,0,output)
            self.assertIn('0x00000000 (preserved',output)
            self.assertIn('no effective override is assumed',output)
        finally:shutil.rmtree(root)

    def test_failed_upload_propagates(self):
        root=tempfile.mkdtemp()
        try:
            for d in ('bin','scripts'):os.mkdir(os.path.join(root,d))
            for path,body in [('bin/halcmd','exit 0'),('scripts/py3_run.sh','exit 0'),
                              ('bin/ethercat','echo stub-master-missing >&2; exit 7')]:
                dest=os.path.join(root,path)
                with open(dest,'w') as f:f.write('#!/bin/bash\n'+body+'\n')
                os.chmod(dest,0o755)
            env=os.environ.copy();env['PP_ROOT']=root
            proc=subprocess.Popen(['bash',SCRIPT,'check'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,env=env)
            output=proc.communicate()[0].decode()
            self.assertEqual(proc.returncode,7)
            self.assertIn('stub-master-missing',output)
            self.assertIn('SDO upload failed',output)
            self.assertNotIn('Unexpected spindle vendor',output)
        finally:shutil.rmtree(root)
if __name__=='__main__':unittest.main()
