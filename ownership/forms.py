"""English-only guest questions and shared input validation."""
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit
from .core import AppError, bounded, CATEGORIES, STAGES, NETWORKS, RAISE_STATES

LABELS = {
    'gaming':'Gaming', 'defi':'DeFi', 'prediction':'Prediction markets',
    'tokenization':'Tokenization', 'infra':'Infrastructure', 'payments':'Payments',
    'consumer':'Consumer', 'other':'Other', 'idea':'Idea', 'building':'Building',
    'beta':'Beta', 'live':'Live product', 'na':'Not applicable',
    'devnet':'Devnet', 'testnet':'Testnet', 'mainnet':'Mainnet',
    'not_started':'No current plan', 'planning':'Planning', 'ongoing':'In progress',
    'success':'Successful', 'partial':'Partially funded', 'unsuccessful':'Unsuccessful',
    'yes':'Yes', 'no':'No', 'undecided':'Undecided', 'considering':'Considering',
    'later':'I will respond later', 'unknown':'Not known yet',
    'general':'General information', 'raise':'Raise review', 'both':'Both',
    'new':'New', 'reviewing':'Under review', 'followup':'Follow-up', 'accepted':'Accepted',
    'closed':'Closed', 'planned':'Planned', 'invited':'Invited', 'confirmed':'Confirmed',
    'attended':'Attended', 'declined':'Declined', 'remove':'Remove', 'open':'Open',
    'doing':'In progress', 'done':'Done', 'cancelled':'Cancelled', 'completed':'Completed',
    'internal':'Internal note', 'guest':'Message to representative', 'radio':'Radio',
    'roadshow':'Roadshow', 'podcast':'Podcast', 'meeting':'Meeting', 'campaign':'Campaign',
}


def label(value):
    return LABELS.get(value, value)


FIELDS = {
    'name':('What is your project called?', 'text', True),
    'categories':('Which areas do you work in? Select one or more.', CATEGORIES, True),
    'motivation':('In 1 or 2 sentences, what need led you to build this?', 'text', False),
    'stage':('What stage is the product at?', STAGES, True),
    'network':('If it uses a blockchain, which environment is it on? This is separate from product stage.', NETWORKS, True),
    'website':('Share the product or demo URL, or skip if it is not available.', 'url', False),
    'socials':('Share project socials and team contacts you want us to use. One per line.', 'socials', False),
    'raise_status':('What is the status of your current or most recent raise?', RAISE_STATES + ['unknown'], True),
    'retry':('Are you planning another attempt?', ['yes', 'no', 'undecided'], True),
    'platform':('Which platform or method did you use, or plan to use?', 'text', False),
    'currency':('Choose the currency. Target and amount raised are recorded separately.', ['USD','USDC','SOL','ETH','EUR','OTHER','unknown'], True),
    'currency_code':('Enter the currency code, such as GBP.', 'currency', True),
    'target_amount':('What is the raise target? Enter a number or skip.', 'amount', False),
    'raised_amount':('How much has been received so far? Enter a number or skip if unknown.', 'amount', False),
    'metadao':('Have you considered MetaDAO for your raise?', ['yes','no','considering','unknown'], True),
}


def questions(purpose, answers):
    q = ['name','categories','motivation','stage','network','website','socials']
    if purpose == 'general':
        return q
    q += ['raise_status']
    state = answers.get('raise_status')
    if state in ('partial','unsuccessful'):
        q += ['retry']
    if state not in (None,'not_started','unknown'):
        q += ['platform','currency']
        currency = answers.get('currency')
        if currency == 'OTHER':
            q += ['currency_code']
        if currency not in (None,'unknown'):
            q += ['target_amount']
            if state in ('ongoing','success','partial','unsuccessful'):
                q += ['raised_amount']
    q += ['metadao']
    return q


def validate(field, value):
    prompt, kind, required = FIELDS[field]
    if value is None:
        if required:
            raise AppError('This field is required.')
        return None
    if field == 'categories':
        if not isinstance(value,list) or not value or not set(value) <= set(CATEGORIES):
            raise AppError('Select at least one area.')
        return sorted(set(value))
    if isinstance(kind,list):
        if value not in kind:
            raise AppError('Select an option from the current step.')
        return value
    value = bounded(value, 100 if field == 'name' else 1200, required)
    if not value and not required:
        return None
    if kind == 'url':
        try:
            u = urlsplit(value)
            if u.scheme not in ('https','http') or not u.hostname or u.username or u.password or any(c.isspace() for c in value):
                raise ValueError()
        except ValueError:
            raise AppError('Use a URL starting with https:// or http://.') from None
    if kind == 'socials':
        for line in value.splitlines():
            if line.startswith('@') and 2 <= len(line) <= 64 and all(c.isalnum() or c == '_' for c in line[1:]):
                continue
            validate('website',line)
    if kind == 'currency':
        if not value.isascii() or not value.isalpha() or not 2 <= len(value) <= 12:
            raise AppError('Enter a valid currency code.')
        return value.upper()
    if kind == 'amount':
        try:
            # International digits remain valid input; all built-in copy is English.
            digits = ''.join(chr(i) for i in range(0x06f0,0x06fa))
            amount = Decimal(value.replace(',','').translate(str.maketrans(digits,'0123456789')))
            if not amount.is_finite() or amount < 0 or amount > Decimal('1e15') or amount.as_tuple().exponent < -9:
                raise ValueError()
            return format(amount,'f')
        except (InvalidOperation,ValueError):
            raise AppError('Enter zero or a positive number, with up to 9 decimal places.') from None
    return value


def split_answers(purpose, answers, contact):
    current = questions(purpose,answers)
    data = {f:validate(f,answers.get(f)) for f in current}
    general = {k:data.get(k) for k in ['name','categories','motivation','stage','network','website','socials']}
    general['contact'] = contact
    fund = {k:v for k,v in data.items() if k not in general} if purpose != 'general' else {}
    if fund.get('currency') == 'OTHER':
        fund['currency'] = fund.pop('currency_code')
    fund.pop('currency_code',None)
    return general,fund
