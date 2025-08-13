import http.client, urllib.parse
import json
import os
from dotenv import load_dotenv
from web3 import Web3
from web3.types import TxParams
from eth_abi.abi import decode, encode
from eth_utils import decode_hex
from eth_keys import keys
import time
from datetime import datetime
import pandas as pd
from dateutil.relativedelta import relativedelta


load_dotenv(".env", override=True)
W3 = Web3(Web3.HTTPProvider(os.environ.get("RPC")))
CHAIN_ID = 1514

with open('./abis/timelock_vest_vault.json', 'r') as f:
    VAULT_ABI = json.load(f)
with open('./abis/stake_reward_receiver.json', 'r') as f:
    STAKE_RECEIVER_ABI = json.load(f)

def find_staking_recipient(address):
    vault = W3.eth.contract(address=W3.to_checksum_address(address), abi=VAULT_ABI)
    recipient = vault.functions.stakingRewardReceiver().call()
    print(f"{recipient}")
    return recipient


def find_claimable_balances(address):
    vault = W3.eth.contract(address=W3.to_checksum_address(address), abi=VAULT_ABI)
    reward = vault.functions.claimableStakingRewards().call()
    return reward


def find_claimable_times(address):
    vault = W3.eth.contract(address=W3.to_checksum_address(address), abi=VAULT_ABI)
    reward = vault.functions.getStakingRewardClaimableStartTime().call()
    return reward


def find_unlock_time(address):
    vault = W3.eth.contract(address=W3.to_checksum_address(address), abi=VAULT_ABI)
    unlock_schedule = vault.functions.unlocking().call()
    return unlock_schedule


def find_withdrawn(address):
    vault = W3.eth.contract(address=W3.to_checksum_address(address), abi=VAULT_ABI)
    withdrawn = vault.functions.withdrawn().call()
    return withdrawn


def find_allocation(address):
    vault = W3.eth.contract(address=W3.to_checksum_address(address), abi=VAULT_ABI)
    allocation = vault.functions.allocation().call()
    return allocation


def fetch_eth(address):
    eth_balance = W3.eth.get_balance(W3.to_checksum_address(address))/1e18
    return eth_balance


def find_unlock_at_that_time(address, ts):
    vault = W3.eth.contract(address=W3.to_checksum_address(address), abi=VAULT_ABI)
    unlocked_amount = round(vault.functions.getUnlockedAmount(ts).call()/1e18)
    return unlocked_amount


def return_keccak(entry):
    inputs = [i['type'] for i in entry['inputs']]
    message = f"{entry['name']}({','.join(inputs)})"
    keccak = Web3.keccak(text=message)
    if entry['type'] == 'function':
        keccak = keccak[:4]
    return keccak.hex(), inputs


def unlock_schedule(start_month, cliff_months, duration_months, cliff_percentage, allocation, address, cap=None, lookup=False):
    unlocked = []
    month = start_month
    cliff_fraction = cliff_percentage/10000
    unlocked_so_far = 0
    for m in range(duration_months + 1):
        this_month = {'month': month}
        if m < cliff_months:
            this_month['unlocked'] = 0
            this_month['delta'] = 0
        else:
            total_after_cliff = duration_months - cliff_months
            now_after_cliff = m - cliff_months
            cliff_amount = allocation * cliff_fraction
            if cliff_fraction < 1:
                noncliff_amount = allocation * (1 - cliff_fraction) * now_after_cliff/total_after_cliff
            else:
                noncliff_amount = 0
            total_unlocked_by_this_point = cliff_amount + noncliff_amount
            this_month['unlocked'] = total_unlocked_by_this_point
            if cap is None:
                this_month['delta'] = total_unlocked_by_this_point - unlocked_so_far
            else:
                this_month['delta'] = min(total_unlocked_by_this_point, cap) - min(unlocked_so_far, cap)
            unlocked_so_far = total_unlocked_by_this_point
        if lookup:
            answer = find_unlock_at_that_time(address, int(month.timestamp()))
            this_month['answer'] = answer
        month += relativedelta(months=1)
        unlocked.append(this_month)
    unlocked = pd.DataFrame(unlocked)
    unlocked['address'] = address
    unlocked['cap'] = cap
    return unlocked


def return_keccak_by_name(name='StakingRewardsClaimed'):
    for a in VAULT_ABI:
        if 'name' in a:
            if a['name'] == 'StakingRewardsClaimed':
                return return_keccak(a)
    return None


def bytecode(address):
    bytecode = W3.eth.get_code(W3.to_checksum_address(address))
    return bytecode



def find_staking_recipients():
    data = pd.read_csv("savedata/all_staking_contracts_uploaded.csv")
    addresses = data["CREATED_ADDRESS"].tolist()
    recipients = {}
    for address in addresses:
        recipients[address] = find_staking_recipient(address)
    recipients = pd.DataFrame.from_dict(recipients, orient='index').reset_index()
    recipients.columns = ['address', 'recipient']
    recipients.to_csv("savedata/staking_recipients.csv")

    balances = {}
    for recipient in recipients.recipient.unique():
        balances[recipient] = fetch_eth(recipient)
    balances = pd.DataFrame.from_dict(balances, orient='index').reset_index()
    balances.columns = ['recipient', 'balance']
    balances.sort_values('balance', ascending=False, inplace=True)
    balances.to_csv('savedata/staking_reward_balances.csv', index=False)

    claimable_balances = {}
    for address in addresses:
        claimable_balances[address] = find_claimable_balances(address)
    claimable_balances = pd.DataFrame.from_dict(claimable_balances, orient='index').reset_index()
    claimable_balances.columns = ['address', 'claimable']
    claimable_balances['claimable'] /= 1e18
    claimable_balances['claimable'] = claimable_balances['claimable'].apply(lambda x: round(x, 1))
    claimable_balances.sort_values('claimable', ascending=False, inplace=True)
    claimable_balances.to_csv('savedata/claimable_balances.csv', index=False)

    claimed = pd.read_csv("savedata/claimed.csv")
    claimed['claimed'] = claimed['DATA'].apply(lambda x: int(x, 16)/1e18)
    claimed.to_csv("savedata/claimed.csv", index=False)

    unlock_times = {}
    for address in addresses:
        unlock_times[address] = find_unlock_time(address)
    unlock_times = pd.DataFrame.from_dict(unlock_times, orient='index').reset_index()
    unlock_times.columns = ['address', 'start', 'duration_months', 'end', 'cliff', 'cliff_months', 'cliff_percentage']

    allocations = {}
    for address in addresses:
        allocations[address] = round(find_allocation(address)/1e18)
    allocations = pd.DataFrame.from_dict(allocations, orient='index').reset_index()
    allocations.columns = ['address', 'allocation']

    withdrawn = {}
    for address in addresses:
        withdrawn[address] = round(find_withdrawn(address)/1e18)
    withdrawn = pd.DataFrame.from_dict(withdrawn, orient='index').reset_index()
    withdrawn.columns = ['address', 'withdrawn']

    vault_balances = {}
    for address in addresses:
        vault_balances[address] = fetch_eth(address)
    vault_balances = pd.DataFrame.from_dict(vault_balances, orient='index').reset_index()
    vault_balances.columns = ['address', 'vault_balance']


    claimable_times = {}
    for address in addresses:
        claimable_times[address] = find_claimable_times(address)
    claimable_times = pd.DataFrame.from_dict(claimable_times, orient='index').reset_index()
    claimable_times.columns = ['address', 'claimable_time']
    claimable_times.sort_values('claimable', ascending=False, inplace=True)
    claimable_times.to_csv('savedata/claimable_times.csv', index=False)

    claimable = pd.merge(claimable_times, claimable_balances, how='outer', on='address')
    claimable = pd.merge(claimable, recipients, how='outer', on='address')
    claimable = pd.merge(claimable, balances, how='outer', on='recipient')
    claimable = pd.merge(claimable, unlock_times, how='outer', on='address')
    claimable = pd.merge(claimable, allocations, how='outer', on='address')
    claimable = pd.merge(claimable, withdrawn, how='outer', on='address')
    claimable = pd.merge(claimable, vault_balances, how='outer', on='address')
    claimable.to_csv("savedata/claimable.csv", index=False)


    claimable = pd.read_csv("savedata/claimable.csv")
    vault_funding = pd.read_csv("savedata/vault_funding.csv")
    vault_funding.columns = ['address', 'funding']
    claimable = pd.merge(claimable, vault_funding, how='left', on='address')
    claimable['start_month'] = claimable['start'].apply(lambda x: datetime.fromtimestamp(x))

    unlocks = pd.DataFrame()
    for i, row in claimable.iterrows():
        unlock = unlock_schedule(
            row.start_month,
            row.cliff_months,
            row.duration_months,
            row.cliff_percentage,
            row.allocation,
            row.address,
            cap=None,
            lookup=False
        )
        unlocks = pd.concat([unlocks, unlock], ignore_index=True)
        print(f'{datetime.now()} {i}')

    unlocks.to_csv('savedata/unlocks_for_each.csv', index=False)
    unlocks = unlocks.groupby('month').agg({'delta': 'sum'}).reset_index()
    unlocks.sort_values('month', inplace=True)
    unlocks['cumulative'] = unlocks['delta'].cumsum()

    unlocks_capped = pd.DataFrame()
    for i, row in claimable.iterrows():
        unlock = unlock_schedule(
            row.start_month,
            row.cliff_months,
            row.duration_months,
            row.cliff_percentage,
            row.allocation,
            row.address,
            cap=row.funding,
            lookup=False
        )
        unlocks_capped = pd.concat([unlocks_capped, unlock], ignore_index=True)
        print(f'{datetime.now()} {i}')

    unlocks_capped.to_csv('savedata/capped_unlocks_for_each.csv', index=False)
    unlocks_capped = unlocks_capped.groupby('month').agg({'delta': 'sum'}).reset_index()
    unlocks_capped.sort_values('month', inplace=True)
    unlocks_capped['cumulative'] = unlocks_capped['delta'].cumsum()

    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    plt.step(unlocks.month, unlocks.cumulative/1e6, color='navy', where='post', label='allocation')
    plt.step(unlocks_capped.month, unlocks_capped.cumulative/1e6, color='salmon', where='post', label='allocation (given the underfunding)')
    plt.axvline(datetime(2025, 4, 10), color='red', linestyle=':', linewidth=2, label='128mm units on Apr 10th 2025')
    plt.axvline(datetime(2026, 2, 13), color='orange', linestyle=':', linewidth=2, label='62mm units on Feb 13th 2026')
    plt.legend()
    plt.ylabel('Unlocked Tokens (mm)')
    plt.title('IP Unlock Schedule (per the Timelock Contracts)')
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%b%Y'))
    plt.gca().xaxis.set_major_locator(mdates.MonthLocator(interval=12))
    plt.show()

    staking_periods = pd.read_csv('savedata/staking_periods.csv')
    staking_periods.columns = [c.lower() for c in staking_periods.columns]
    staking_periods['num_staked_tkns'] = staking_periods['stake_amount'].apply(lambda s: int(s, 16) / 1e18)
    staking_periods['dt'] = pd.to_datetime(staking_periods['day'], dayfirst=True) + staking_periods['hour'].apply(lambda h: pd.Timedelta(hours=h))
    staking_periods['unlock_dt'] = staking_periods['dt'] + staking_periods['staking_days'].apply(lambda d: pd.Timedelta(days=d))
    staking_periods.to_csv('savedata/staking_periods_for_each.csv', index=False)
    staking_periods = staking_periods[staking_periods['staking_days'] != 0].reset_index(drop=True)
    staking_periods = staking_periods.groupby('unlock_dt').agg({'num_staked_tkns':'sum'}).reset_index()
    staking_periods.sort_values('unlock_dt', inplace=True)
    staking_periods['cum_staked_tkns'] = staking_periods['num_staked_tkns'].cumsum()

    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    plt.step(staking_periods.unlock_dt, staking_periods.cum_staked_tkns/1e6, color='navy', where='post', label='unstakable')
    plt.axvline(datetime(2026, 2, 16), color='orange', linestyle=':', linewidth=2, label='30mm units on Feb 13th 2026')
    plt.legend()
    plt.ylabel('Unlocked Tokens (mm)')
    plt.title('Unlock Schedule for Tokens Locked by Validator')
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%b%Y'))
    plt.gca().xaxis.set_major_locator(mdates.MonthLocator(interval=4))
    plt.show()

    contracts = [
        '0xEB602035F7D6e91c5b39C7c9E87055df546b16FF',
        '0x5599644993C2056c39bFf55c8578f898F70DFbc9',
        '0x38865EFdd19b8eCd0dede3422D0c51580aAfd2E5',
        '0xD009F6544324A3686BeD433BC874E735D0E616A6',
        '0xBB5400b6a7E6E4766f701d1dd4e19116f3C27B91',
        '0x32D39Bd31BDE7a41C9c39D60CDc7dB838d815BBD',
        '0xD01315bf073919990EEE0d6Cbdd771DB92923BB8',
        '0x260F0EC32C13450fBA1f2b9a3Ea74301fB8E733e',
        '0x006B1A78e57ae93dE6D59f743D2D57Fc564FD2Ce',
        '0xa55256C7a140C15150921D8D416387D61F1AFF61',
        '0xc1344Ab7B6eBe62E677536819062d2009249e945',
        '0xEF54E2bd253F62A157f758c951C01Fccac89965a',
        '0x4421C909A7dddBaD7CcC046A5ed88196A0014768',
        '0xA6404eCEb1B9f38350436dB6A849a6e9e425C591',
        '0x0caCB84e5eBB62246F2D3A8446e1ae00cD7BfEc0',
        '0x33a1Aad442f941908e3A6Df1c5Ba9E3cB939D3C9',
        '0x6A8e273C0Adc9fF57638A4cb447ec5886FD5acd3',
        '0x42b8aB83BDEf9BAdAeC2E59C397FDAc74f0b9b95',
        '0xC7c942A46ba3b7CFBa3681303Fbd546B818DeEb9',
        '0xC172afD13550Eff273b20fed67001C5d1A113ab1',
        '0xfC213B6DDaA860CA41831730Ef6eA7D5AAd9BA5b',
        '0x6677881d945BFD12195B0d51A82B7Ae93A5b5c90',
        '0x18dDeB46e3E774c447444C874dc1053Ad3578F91',
        '0x3107E481DFC6818c711395b3C8ADc591bae8a6AF',
        '0xe0bC64c5A8Ec0dCD08C185ff975E97d589e6Bf87',
        '0x01be2099e1043C45221D2B3b4037472E38E50184',
        '0xEB04Ea9D2856f48696081F4a0B2DD880d5f3104C',
        '0xd4aF4857e003e5FfC6dA5AbAc7015171690d1A18',
        '0x3C30859fE8De34c99b49d0afE7Ac9eD148E1C315',
        '0xcC5C7794c51489c524adbF01917616fa008b24D4', # MM?
        '0x380ef8A593790B1553D10f9cf1813940B7301Fe7',
        '0x40C590AF59F3a869D6E3c9008E48289fcd8D29D2',
        '0xC3f3a6FC969c77543d39E5fF1649185F218E0422',
        '0x1CFf7365145c6DB896df208C477BA5a7278c818b',
        '0xa2D324aB7F596717a36293208B283c399EAf3a7b',
        '0x9Ff045Fe99554602C1ec78C4365ED2BD70591808',
        '0x6530B70a9583b2E9229CCa10c19a13F59ef6F410',
        '0xB9fE7f43DA1C92dC8204dc8F064A75F81B6af04B',
        '0xf1F45C6D61B0A5a4C5d86e4C923B9F0bB45732FF',
        '0x470507B37215659cECdEA3b0b5C98664c86D4D2C',
        '0x23eC44511347093F15Db7A5AaCDCaa20B6E2e441',
    ]

    bytecodes = {}
    for c in contracts:
        bytecodes[c] = bytecode(c)
    bytecodes = pd.DataFrame.from_dict(bytecodes, orient='index')


    import requests
    response = requests.get('https://raw.githubusercontent.com/piplabs/story-geth/refs/heads/main/core/gendata/story/genesis.json')
    genesis = response.json()
    accs = genesis['alloc']
    balances = {}
    for a in accs:
        balance = round(int(accs[a]['balance'], 16)/1e18)
        if balance >= 1000:
            balances[a] = balance
    balances = pd.DataFrame.from_dict(balances, orient='index').reset_index()
    balances.columns = ['address', 'balance']
    balances.sort_values('balance', ascending=False, inplace=True)
    balances.to_csv('./savedata/genesis_balances.csv', index=False)

    import requests
    response = requests.get('https://www.storyscan.io/api/v2/addresses/')
    accs = response.json()['items']
    all_accs = accs.copy()
    num_accs = len(accs)
    supply = sum([int(a['coin_balance'])/1e18 for a in accs])
    for i in range(30):
        time.sleep(1)
        last = accs[-1]
        print(f'run: {i}, supply: {int(supply)}')
        param = f'fetched_coin_balance={last['coin_balance']}&hash={last['hash']}&items_count={num_accs}&transactions_count={last['transactions_count']}'
        response = requests.get(f'https://www.storyscan.io/api/v2/addresses/?{param}')
        accs = response.json()['items']
        supply += sum([int(a['coin_balance'])/1e18 for a in accs])
        all_accs.extend(accs)
        num_accs += len(accs)

    keys = ['transaction_count', 'coin_balance', 'hash', 'is_contract']
    all_accs_df = pd.DataFrame([[a[k] for k in a if k in keys] for a in all_accs], columns=keys)
    all_accs_df = all_accs_df.groupby('hash').first().reset_index()
    all_accs_df['num_tokens'] = all_accs_df['coin_balance'].apply(lambda c: round(int(c)/1e18))
    print(all_accs_df['num_tokens'].sum())

    all_accs_df['hash'] = all_accs_df['hash'].str.lower()
    balances['address'] = balances['address'].str.lower()
    genesis_accs = pd.merge(all_accs_df, balances, right_on='address', left_on='hash', how='inner')
    genesis_accs['num_tokens'].sum()

