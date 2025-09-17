''' pooferMappings is an object containing poofer names as attributes, where each 
attribute value is a string of 3 digits that translate to the poofer's address on the 
poofer control boards.  The first and second digits is the board number in hexadecimal, 
and the third digit is the channel on that board (there are 8 channels per board).
'''
# XXX - probably want to have this as a modifyable JSON file, with a UI to change the mapping.

mappings = {}
mappings['C1']="011"
mappings['C2']="012"
mappings['C3']="013"
mappings['C4']="014"
mappings['C5']="015"
mappings['C6']="016"
mappings['C_HAIR1']="017"
mappings['C_HAIR2']="018"
mappings['C_HAIR3']="021"
mappings['C_HAIR4']="022"
mappings['O_EYES']="031"
mappings['O_WINGS']="032"
mappings['O1']="033"
mappings['O2']="034"
mappings['O3']="035"
mappings['M_TAIL']="041"
mappings['M1']="042"
mappings['M2']="043"
mappings['M3']="044"
mappings['P1']="051"
mappings['P2']="052"
mappings['P3']="053"
mappings['P4']="054"
