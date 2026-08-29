"""Load one verified mapping bundle and transform a payload."""

from open_mapping import Mapper

mapper = Mapper.load("customer.omc")
print(mapper.transform({"customerId": "C-1001", "fullName": "Ada Lovelace"}))
