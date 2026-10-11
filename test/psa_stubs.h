// Enkel voor de Linux hosttest. De systeembibliotheek mbedtls 2.28 mist de multipart
// PSA AEAD functies die dsmr_parser enkel gebruikt voor versleutelde meters (Luxemburg).
// Fluvius meters sturen onversleuteld, dus deze stubs worden nooit uitgevoerd.
#pragma once
#include <psa/crypto.h>
extern "C" {
psa_status_t psa_aead_decrypt_setup(psa_aead_operation_t *, mbedtls_svc_key_id_t, psa_algorithm_t) { return PSA_ERROR_NOT_SUPPORTED; }
psa_status_t psa_aead_set_nonce(psa_aead_operation_t *, const uint8_t *, size_t) { return PSA_ERROR_NOT_SUPPORTED; }
psa_status_t psa_aead_update_ad(psa_aead_operation_t *, const uint8_t *, size_t) { return PSA_ERROR_NOT_SUPPORTED; }
psa_status_t psa_aead_update(psa_aead_operation_t *, const uint8_t *, size_t, uint8_t *, size_t, size_t *) { return PSA_ERROR_NOT_SUPPORTED; }
psa_status_t psa_aead_verify(psa_aead_operation_t *, uint8_t *, size_t, size_t *, const uint8_t *, size_t) { return PSA_ERROR_NOT_SUPPORTED; }
psa_status_t psa_aead_abort(psa_aead_operation_t *) { return PSA_SUCCESS; }
}
