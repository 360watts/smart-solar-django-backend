from django.urls import reverse
from rest_framework.test import APITestCase
from api.models import GatewayConfig, SlaveDevice, RegisterMapping


class ApiFlowTests(APITestCase):
	def setUp(self):
		gc = GatewayConfig.objects.create(config_id="cfg-test")
		s1 = SlaveDevice.objects.create(gateway_config=gc, slave_id=1, device_name="Solar Inverter")
		RegisterMapping.objects.create(slave=s1, label="dc_voltage", address=100, num_registers=2, function_code=3, data_type=4)

	def test_provision_and_config_and_heartbeat(self):
		# Provision
		prov_resp = self.client.post(
			reverse("provision"),
			{"device_serial": "dev-abc", "pub_key_alg": "RSA", "csr_pem": "-----BEGIN CSR-----X"},
			format="json",
		)
		self.assertEqual(prov_resp.status_code, 200)
		# Get config
		cfg_resp = self.client.post(
			reverse("gateway_config"),
			{"deviceId": "dev-abc", "firmwareVersion": "1.0.0", "configVersion": ""},
			format="json",
		)
		self.assertEqual(cfg_resp.status_code, 200)
		config_id = cfg_resp.json()["configId"]
		# Heartbeat with same config (no update)
		hb_resp = self.client.post(reverse("heartbeat"), {"deviceId": "dev-abc", "configId": config_id}, format="json")
		self.assertEqual(hb_resp.status_code, 200)
		self.assertFalse(hb_resp.json()["commands"]["updateConfig"])

	def test_telemetry_ingest(self):
		# Ensure device provisioned implicitly
		telem_resp = self.client.post(
			reverse("telemetry_ingest"),
			{
				"deviceId": "dev-xyz",
				"timestamp": "2025-11-18T10:30:00Z",
				"dataType": "dc_voltage",
				"value": 48.5,
				"unit": "V",
			},
			format="json",
		)
		self.assertEqual(telem_resp.status_code, 201)
		latest_resp = self.client.get(reverse("telemetry_latest", args=["dev-xyz"]))
		self.assertEqual(latest_resp.status_code, 200)
		self.assertGreaterEqual(len(latest_resp.json()), 1)
