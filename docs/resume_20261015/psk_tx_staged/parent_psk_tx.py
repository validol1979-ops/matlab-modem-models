def verified_psk_tx_uvm_artifacts(data,root=ROOT):
    from run_psk_tx_uvm import PROFILES,TX_SCENARIOS,CONTROLS,parameters
    if not isinstance(data,dict) or data.get('profiles')!='all' or not isinstance(data.get('records'),dict):
        raise RuntimeError('All PSK/QAM TX UVM profiles required')
    records=data['records']
    for name,profile in PROFILES.items():
        bits=(profile.alphabet-1).bit_length();mask=(1<<profile.alphabet)-1
        for active in (1,0):
            for scenario in TX_SCENARIOS:
                row=records.get(f'{name}_{scenario}_reset_{active}')
                if (not isinstance(row,dict) or row.get('profile')!=name+'_tx' or row.get('scenario')!=scenario
                        or type(row.get('reset_active')) is not int or row['reset_active']!=active
                        or row.get('label_bits')!=bits or row.get('labels_seen_mask')!=mask or row.get('tx_parameters')!=parameters(name)
                        or row.get('per_frame')!=[dict(frame=f,input_symbols=n,output_samples=8*n+32) for f,n in enumerate((1,2,33,192,768))]
                        or row.get('held_last_resets')!=int(scenario=='outreset')):
                    raise RuntimeError('Incomplete PSK/QAM TX UVM profile/mapper/label/frame/reset coverage')
            for key,(tag,_,_) in CONTROLS.items():
                row=records.get(f'{name}_negative_{key}_reset_{active}')
                if (not isinstance(row,dict) or row.get('detected_tag')!=tag
                        or type(row.get('returncode')) is not int or row['returncode']==0):
                    raise RuntimeError('Incomplete PSK/QAM TX UVM negative controls')
    if not data.get('artifact_hashes'):raise RuntimeError('Missing PSK/QAM TX UVM artifacts')
    return verified_suite_artifacts(data,root)
