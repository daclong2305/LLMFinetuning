import unittest
from unittest.mock import Mock, patch
from text2sql_demo.experiment.backends import BedrockBackend, BackendError
class BedrockTests(unittest.TestCase):
 def test_converse(self):
  client=Mock(); client.converse.return_value={'stopReason':'end_turn','output':{'message':{'content':[{'text':'{"sql":"SELECT 1"}'}]}},'usage':{'inputTokens':12,'outputTokens':6}}
  with patch('boto3.session.Session.client',return_value=client):
   result=BedrockBackend({'provider':'bedrock','model':'test','region':'us-east-1'}).generate([{'role':'system','content':'SQL'},{'role':'user','content':'question'}])
  self.assertEqual(result['input_tokens'],12); self.assertEqual(result['output_tokens'],6); self.assertIsNone(result['cost_usd'])
  self.assertEqual(client.converse.call_args.kwargs['system'],[{'text':'SQL'}])
 def test_safe_error(self):
  with patch('boto3.session.Session.client',side_effect=Exception('sensitive provider content')):
   with self.assertRaises(BackendError) as error: BedrockBackend({'provider':'bedrock','model':'test'}).generate([])
  self.assertNotIn('sensitive',str(error.exception))
if __name__=='__main__': unittest.main()
